import base64
import datetime as dt

import dash
from dash import html, dcc, callback, Output, Input, State, ctx
import dash_bootstrap_components as dbc

import config
from services.processor import process_upload

dash.register_page(__name__, path="/upload", name="Upload")

layout = html.Div(
    [
        html.H3("Upload Order Sheets", className="mb-3"),
        dbc.Row(
            [
                dbc.Col(
                    dbc.Input(
                        id="retailer-name-input",
                        placeholder="Retailer / M/s. name - optional, auto-detected from the sheet if left blank",
                        type="text",
                    ),
                    md=6,
                    xs=12,
                )
            ],
            className="mb-3",
        ),
        dbc.Row(
            [
                dbc.Col(
                    dcc.Upload(
                        id="upload-camera",
                        children=html.Div(
                            ["📷", html.Br(), "Take Photo"], className="text-center fs-5"
                        ),
                        style={
                            "width": "100%",
                            "height": "110px",
                            "display": "flex",
                            "alignItems": "center",
                            "justifyContent": "center",
                            "borderWidth": "2px",
                            "borderStyle": "dashed",
                            "borderColor": "#2c3e50",
                            "borderRadius": "10px",
                            "marginBottom": "12px",
                        },
                        multiple=False,
                        accept="image/*",
                    ),
                    xs=12,
                    md=6,
                ),
                dbc.Col(
                    dcc.Upload(
                        id="upload-files",
                        children=html.Div(
                            ["🖼️", html.Br(), "Upload from Gallery / Files (bulk supported)"],
                            className="text-center fs-5",
                        ),
                        style={
                            "width": "100%",
                            "height": "110px",
                            "display": "flex",
                            "alignItems": "center",
                            "justifyContent": "center",
                            "borderWidth": "2px",
                            "borderStyle": "dashed",
                            "borderRadius": "10px",
                            "marginBottom": "12px",
                        },
                        multiple=True,
                        accept="image/*,.pdf",
                    ),
                    xs=12,
                    md=6,
                ),
            ]
        ),
        html.P(
            "On your phone, 'Take Photo' opens the camera directly. Select many files at once "
            "through 'Upload from Gallery / Files' - they process one at a time with live progress "
            "below. Already-processed images are detected and skipped automatically.",
            className="text-muted small",
        ),
        dcc.Store(id="upload-queue", data=[]),
        dcc.Store(id="upload-total", data=0),
        dcc.Store(id="upload-results", data=[]),
        dcc.Interval(id="upload-tick", interval=400, disabled=True, n_intervals=0),
        html.Div(id="upload-progress-text", className="text-muted small mb-2"),
        dbc.Progress(id="upload-progress-bar", value=0, className="mb-3", style={"height": "6px"}, animated=True, striped=True),
        html.Div(id="upload-results-display"),
    ]
)


def _save_uploaded_file(filename, content_string) -> str:
    decoded = base64.b64decode(content_string)
    timestamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S%f")
    safe_name = f"{timestamp}_{filename}"
    out_path = config.UPLOADS_DIR / safe_name
    with open(out_path, "wb") as f:
        f.write(decoded)
    return str(out_path)


def _queue_items(contents_list, filenames_list):
    return [{"filename": f, "content": c} for c, f in zip(contents_list, filenames_list)]


@callback(
    Output("upload-queue", "data", allow_duplicate=True),
    Output("upload-total", "data", allow_duplicate=True),
    Output("upload-results", "data", allow_duplicate=True),
    Output("upload-tick", "disabled", allow_duplicate=True),
    Input("upload-camera", "contents"),
    State("upload-camera", "filename"),
    State("upload-queue", "data"),
    prevent_initial_call=True,
)
def stage_camera_upload(contents, filename, existing_queue):
    if not contents:
        return dash.no_update, dash.no_update, dash.no_update, dash.no_update
    new_items = _queue_items([contents], [filename])
    queue = (existing_queue or []) + new_items
    return queue, len(queue), [], False


@callback(
    Output("upload-queue", "data", allow_duplicate=True),
    Output("upload-total", "data", allow_duplicate=True),
    Output("upload-results", "data", allow_duplicate=True),
    Output("upload-tick", "disabled", allow_duplicate=True),
    Input("upload-files", "contents"),
    State("upload-files", "filename"),
    State("upload-queue", "data"),
    prevent_initial_call=True,
)
def stage_gallery_upload(list_of_contents, list_of_filenames, existing_queue):
    if not list_of_contents:
        return dash.no_update, dash.no_update, dash.no_update, dash.no_update
    new_items = _queue_items(list_of_contents, list_of_filenames)
    queue = (existing_queue or []) + new_items
    return queue, len(queue), [], False


def _result_to_alert(result: dict):
    kind = result.get("kind")
    filename = result.get("filename", "")
    if kind == "duplicate":
        dup = result["duplicate"]
        when = dup.get("upload_date", "")
        who = f" by {dup['uploaded_by']}" if dup.get("uploaded_by") else ""
        match_word = "identical to" if dup.get("match_type") == "exact" else "looks like a duplicate of"
        return dbc.Alert(
            f"⏭️ {filename}: already processed - {match_word} \"{dup['filename']}\" "
            f"uploaded{who} on {when}. Skipped, nothing re-processed.",
            color="info",
        )
    if kind == "quality_reject":
        return dbc.Alert(f"📵 {filename}: skipped - {result['message']}", color="warning")
    if kind == "error":
        return dbc.Alert(f"❌ {filename}: failed - {result['message']}", color="danger")
    if kind == "partial_error":
        return dbc.Alert(f"⚠️ {filename}: processed with errors - {result['message']}", color="warning")
    return dbc.Alert(
        f"✅ {filename}: {result['rows_found']} X-marked row(s) found across {result['pages']} page(s).",
        color="success",
    )


@callback(
    Output("upload-queue", "data", allow_duplicate=True),
    Output("upload-results", "data", allow_duplicate=True),
    Output("upload-progress-text", "children"),
    Output("upload-progress-bar", "value"),
    Output("upload-tick", "disabled", allow_duplicate=True),
    Input("upload-tick", "n_intervals"),
    State("upload-queue", "data"),
    State("upload-results", "data"),
    State("upload-total", "data"),
    State("retailer-name-input", "value"),
    State("current-user-store", "data"),
    prevent_initial_call=True,
)
def process_next_in_queue(_, queue, results, total, retailer_name, current_user):
    queue = queue or []
    results = results or []
    if not queue:
        return dash.no_update, dash.no_update, dash.no_update, dash.no_update, True

    item = queue[0]
    remaining = queue[1:]
    filename = item["filename"]

    try:
        _, content_string = item["content"].split(",", 1)
        saved_path = _save_uploaded_file(filename, content_string)
        summary = process_upload(
            saved_path,
            retailer_name=(retailer_name or "").strip(),
            uploaded_by=(current_user or "").strip(),
        )
        if summary["duplicates"]:
            for dup in summary["duplicates"]:
                results.append({"kind": "duplicate", "filename": filename, "duplicate": dup})
        elif summary["quality_rejects"]:
            for msg in summary["quality_rejects"]:
                results.append({"kind": "quality_reject", "filename": filename, "message": msg})
        elif summary["errors"]:
            results.append(
                {"kind": "partial_error", "filename": filename, "message": "; ".join(summary["errors"])}
            )
        else:
            results.append(
                {
                    "kind": "success",
                    "filename": filename,
                    "rows_found": summary["rows_found"],
                    "pages": summary["images_created"],
                }
            )
    except Exception as e:
        results.append({"kind": "error", "filename": filename, "message": str(e)})

    done_count = total - len(remaining)
    progress_text = f"Processing {done_count} of {total}..." if remaining else f"Done - {total} file(s) processed."
    progress_val = int((done_count / total) * 100) if total else 100
    return remaining, results, progress_text, progress_val, len(remaining) == 0


@callback(
    Output("upload-results-display", "children"),
    Input("upload-results", "data"),
)
def render_results(results):
    if not results:
        return ""
    return [_result_to_alert(r) for r in reversed(results)]
