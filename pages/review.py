import dash
from dash import html, dcc, callback, Output, Input, State, ALL, ctx
import dash_bootstrap_components as dbc

from services.aggregator import get_review_queue, review_action

dash.register_page(__name__, path="/review", name="Review Queue")

layout = html.Div(
    [
        html.H3("Manual Review Queue", className="mb-2"),
        html.P(
            "Rows below the confidence threshold land here instead of being "
            "auto-accepted into the aggregated totals. Accept, edit, or reject each one.",
            className="text-muted",
        ),
        dcc.Interval(id="review-refresh", interval=4000, n_intervals=0),
        html.Div(id="review-list"),
    ]
)


def _review_row(item):
    row_id = item["id"]
    return dbc.Card(
        dbc.CardBody(
            [
                dbc.Row(
                    [
                        dbc.Col(
                            [
                                html.Div(
                                    [
                                        html.B(f"{item['filename']} "),
                                        html.Span(f"({item['retailer']})", className="text-muted"),
                                    ]
                                ),
                                html.Div(
                                    f"OCR conf {item['ocr_confidence']:.2f} · "
                                    f"Cross conf {item['cross_confidence']:.2f}",
                                    className="small text-muted",
                                ),
                                html.Div(f"Raw row: {item['raw_row_text']}", className="small"),
                            ],
                            md=4,
                        ),
                        dbc.Col(
                            dbc.Input(
                                id={"type": "review-alias", "index": row_id},
                                value=item["product_alias"],
                                placeholder="Product Alias",
                            ),
                            md=3,
                        ),
                        dbc.Col(
                            dbc.Input(
                                id={"type": "review-qty", "index": row_id},
                                value=item["required_quantity"],
                                type="number",
                            ),
                            md=2,
                        ),
                        dbc.Col(
                            [
                                dbc.Button(
                                    "Accept",
                                    id={"type": "review-accept", "index": row_id},
                                    color="success",
                                    size="sm",
                                    className="me-1",
                                ),
                                dbc.Button(
                                    "Reject",
                                    id={"type": "review-reject", "index": row_id},
                                    color="danger",
                                    size="sm",
                                ),
                            ],
                            md=3,
                            className="d-flex align-items-center",
                        ),
                    ]
                )
            ]
        ),
        className="mb-2 shadow-sm",
    )


@callback(Output("review-list", "children"), Input("review-refresh", "n_intervals"))
def render_review_queue(_):
    items = get_review_queue()
    if not items:
        return dbc.Alert("Review queue is empty - everything is auto-accepted. 🎉", color="success")
    return [_review_row(i) for i in items]


@callback(
    Output("review-refresh", "n_intervals"),
    Input({"type": "review-accept", "index": ALL}, "n_clicks"),
    Input({"type": "review-reject", "index": ALL}, "n_clicks"),
    State({"type": "review-alias", "index": ALL}, "value"),
    State({"type": "review-qty", "index": ALL}, "value"),
    State({"type": "review-alias", "index": ALL}, "id"),
    prevent_initial_call=True,
)
def handle_review_actions(accept_clicks, reject_clicks, aliases, qtys, alias_ids):
    triggered = ctx.triggered_id
    if not triggered or not isinstance(triggered, dict):
        return dash.no_update

    row_id = triggered["index"]
    action_type = triggered["type"]

    # find the matching edited alias/qty for this row
    idx = next((i for i, aid in enumerate(alias_ids) if aid["index"] == row_id), None)
    edited_alias = aliases[idx] if idx is not None else None
    edited_qty = qtys[idx] if idx is not None else None

    if action_type == "review-accept":
        review_action(row_id, "edit", edited_alias=edited_alias, edited_qty=edited_qty)
    elif action_type == "review-reject":
        review_action(row_id, "reject")

    return 0
