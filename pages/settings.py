import shutil
from datetime import datetime

import dash
from dash import html, dcc, callback, Output, Input, State
import dash_bootstrap_components as dbc

import config
from database.db import get_setting, set_setting
from services.aggregator import get_users, add_user, remove_user

dash.register_page(__name__, path="/settings", name="Settings")

layout = html.Div(
    [
        html.H3("Settings", className="mb-3"),
        dbc.Card(
            dbc.CardBody(
                [
                    html.H5("Groq Vision Model"),
                    dbc.Label("Groq API Key (leave blank if set via .env GROQ_API_KEY)"),
                    dbc.Input(id="groq-key-input", type="password", placeholder="gsk_..."),
                    dbc.Label("Model name", className="mt-2"),
                    dbc.Input(id="groq-model-input", type="text"),
                    dbc.Button("Save", id="save-groq-btn", color="primary", className="mt-3"),
                    html.Div(id="save-groq-result", className="mt-2"),
                ]
            ),
            className="mb-4 shadow-sm",
        ),
        dbc.Card(
            dbc.CardBody(
                [
                    html.H5("Detection Thresholds"),
                    dbc.Label("OCR confidence threshold (0-1)"),
                    dbc.Input(id="ocr-threshold-input", type="number", min=0, max=1, step=0.05),
                    dbc.Label("Cross confidence threshold (0-1)", className="mt-2"),
                    dbc.Input(id="cross-threshold-input", type="number", min=0, max=1, step=0.05),
                    dbc.Label("Product-master fuzzy match threshold (0-100)", className="mt-2"),
                    dbc.Input(id="fuzzy-threshold-input", type="number", min=0, max=100, step=1),
                    dbc.Label("Product alias regex", className="mt-2"),
                    dbc.Input(id="alias-regex-input", type="text"),
                    dbc.Label("Blur rejection threshold (lower = stricter)", className="mt-2"),
                    dbc.Input(id="blur-threshold-input", type="number", min=0, step=1),
                    dbc.Label("Recurring-shortage alert - flag after this many misses", className="mt-2"),
                    dbc.Input(id="reorder-threshold-input", type="number", min=1, step=1),
                    dbc.Button("Save Thresholds", id="save-thresholds-btn", color="primary", className="mt-3"),
                    html.Div(id="save-thresholds-result", className="mt-2"),
                ]
            ),
            className="mb-4 shadow-sm",
        ),
        dbc.Card(
            dbc.CardBody(
                [
                    html.H5("Team (no password - just attribution)"),
                    html.P(
                        "Names people pick from the dropdown in the top-right when uploading/editing. "
                        "Admin-checked names see the Insights page. This is a convenience list, not a "
                        "login system - anyone can pick any name.",
                        className="text-muted small",
                    ),
                    html.Div(id="users-table"),
                    dbc.Row(
                        [
                            dbc.Col(dbc.Input(id="new-user-name-input", placeholder="Name"), md=5),
                            dbc.Col(dbc.Checklist(id="new-user-admin-check", options=[{"label": "Admin", "value": "admin"}], value=[]), md=3),
                            dbc.Col(dbc.Button("Add / Update", id="add-user-btn", color="primary", size="sm"), md=4),
                        ],
                        className="mt-2 g-2 align-items-center",
                    ),
                    html.Div(id="user-mgmt-result", className="mt-2"),
                ]
            ),
            className="mb-4 shadow-sm",
        ),
        dbc.Card(
            dbc.CardBody(
                [
                    html.H5("Backup"),
                    html.P(f"Database location: {config.DATABASE_PATH}", className="text-muted small"),
                    dbc.Button("📦 Backup Database Now", id="backup-btn", color="secondary"),
                    html.Div(id="backup-result", className="mt-2"),
                ]
            ),
            className="shadow-sm",
        ),
    ]
)


@callback(
    Output("groq-key-input", "value"),
    Output("groq-model-input", "value"),
    Output("ocr-threshold-input", "value"),
    Output("cross-threshold-input", "value"),
    Output("fuzzy-threshold-input", "value"),
    Output("alias-regex-input", "value"),
    Output("blur-threshold-input", "value"),
    Output("reorder-threshold-input", "value"),
    Input("groq-model-input", "id"),  # fires once on page load
)
def load_settings(_):
    return (
        "",
        get_setting("groq_model", config.GROQ_MODEL_DEFAULT),
        float(get_setting("ocr_confidence_threshold", config.DEFAULT_OCR_CONFIDENCE_THRESHOLD)),
        float(get_setting("cross_confidence_threshold", config.DEFAULT_CROSS_CONFIDENCE_THRESHOLD)),
        float(get_setting("fuzzy_match_threshold", 85)),
        get_setting("alias_regex", config.DEFAULT_ALIAS_REGEX),
        float(get_setting("blur_variance_threshold", 40)),
        int(float(get_setting("reorder_alert_min_times", 3))),
    )


@callback(
    Output("save-groq-result", "children"),
    Input("save-groq-btn", "n_clicks"),
    State("groq-key-input", "value"),
    State("groq-model-input", "value"),
    prevent_initial_call=True,
)
def save_groq(n_clicks, api_key, model_name):
    if api_key:
        set_setting("groq_api_key", api_key)
    if model_name:
        set_setting("groq_model", model_name)
    return dbc.Alert("✅ Saved.", color="success", duration=3000)


@callback(
    Output("save-thresholds-result", "children"),
    Input("save-thresholds-btn", "n_clicks"),
    State("ocr-threshold-input", "value"),
    State("cross-threshold-input", "value"),
    State("fuzzy-threshold-input", "value"),
    State("alias-regex-input", "value"),
    State("blur-threshold-input", "value"),
    State("reorder-threshold-input", "value"),
    prevent_initial_call=True,
)
def save_thresholds(n_clicks, ocr_t, cross_t, fuzzy_t, regex, blur_t, reorder_t):
    set_setting("ocr_confidence_threshold", ocr_t)
    set_setting("cross_confidence_threshold", cross_t)
    set_setting("fuzzy_match_threshold", fuzzy_t)
    set_setting("alias_regex", regex)
    if blur_t is not None:
        set_setting("blur_variance_threshold", blur_t)
    if reorder_t is not None:
        set_setting("reorder_alert_min_times", reorder_t)
    return dbc.Alert("✅ Thresholds saved.", color="success", duration=3000)


@callback(
    Output("users-table", "children"),
    Input("user-mgmt-result", "children"),
    Input("save-groq-btn", "id"),  # fires once on load too
)
def render_users_table(_a, _b):
    users = get_users()
    if not users:
        return dbc.Alert("No users yet - add one below.", color="info")
    rows = [
        html.Tr(
            [
                html.Td(u["name"]),
                html.Td("✅" if u["is_admin"] else ""),
                html.Td(dbc.Button("Remove", id={"type": "remove-user-btn", "index": u["name"]}, size="sm", color="danger", outline=True)),
            ]
        )
        for u in users
    ]
    return dbc.Table(
        [html.Thead(html.Tr([html.Th("Name"), html.Th("Admin"), html.Th("")]))] + [html.Tbody(rows)],
        bordered=False,
        hover=True,
        size="sm",
    )


@callback(
    Output("user-mgmt-result", "children"),
    Output("new-user-name-input", "value"),
    Input("add-user-btn", "n_clicks"),
    Input({"type": "remove-user-btn", "index": dash.ALL}, "n_clicks"),
    State("new-user-name-input", "value"),
    State("new-user-admin-check", "value"),
    prevent_initial_call=True,
)
def manage_users(add_clicks, remove_clicks, new_name, admin_checked):
    triggered = dash.ctx.triggered_id
    if triggered == "add-user-btn":
        if not (new_name or "").strip():
            return dbc.Alert("Enter a name first.", color="warning", duration=2000), dash.no_update
        add_user(new_name.strip(), is_admin="admin" in (admin_checked or []))
        return dbc.Alert(f"✅ Saved {new_name.strip()}.", color="success", duration=2000), ""
    if isinstance(triggered, dict) and triggered.get("type") == "remove-user-btn":
        remove_user(triggered["index"])
        return dbc.Alert(f"Removed {triggered['index']}.", color="secondary", duration=2000), dash.no_update
    return dash.no_update, dash.no_update


@callback(
    Output("backup-result", "children"),
    Input("backup-btn", "n_clicks"),
    prevent_initial_call=True,
)
def backup_db(n_clicks):
    try:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = config.DATABASE_DIR / f"stockvision_backup_{timestamp}.db"
        shutil.copy(config.DATABASE_PATH, backup_path)
        return dbc.Alert(f"✅ Backed up to {backup_path}", color="success")
    except Exception as e:
        return dbc.Alert(f"❌ Backup failed: {e}", color="danger")
