import base64
import datetime as dt

import dash
from dash import html, dcc, callback, Output, Input, State
import dash_bootstrap_components as dbc
from flask import session, request

import config
from services.processor import process_upload, get_image_status
from services.browser_detect import detect_in_app_browser

dash.register_page(__name__, path="/upload", name="Upload")

layout = html.Div(
    [
        html.H3("Upload Order Sheets", className="mb-3"),
        html.Div(id="upload-page-browser-warning"),
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
            "through 'Upload from Gallery / Files' - each one uploads instantly and finishes "
            "processing in the background, so you're never stuck waiting on one slow photo. "
            "Already-processed images are detected and skipped automatically.",
            className="text-muted small",
        ),
        # Files waiting to be HANDED OFF (fast: dedup + quality check + record
        # creation only - the slow Groq call itself runs in a background
        # thread, tracked separately in upload-pending below).
        dcc.Store(id="upload-queue", data=[]),
        dcc.Store(id="upload-total", data=0),
        dcc.Store(id="upload-results", data=[]),
        # Images handed off and awaiting a background result: [{"image_id","filename"}].
        # Polled on a slow, cheap timer - each tick is just a DB status read,
        # not the actual processing, so this interval is safe (unlike an
        # earlier version that used an interval to drive the SLOW work
        # itself and could pile up overlapping requests).
        dcc.Store(id="upload-pending", data=[]),
        dcc.Interval(id="upload-poll", interval=1500, disabled=True, n_intervals=0),
        html.Div(id="upload-progress-text", className="text-muted small mb-2"),
        dbc.Progress(id="upload-progress-bar", value=0, className="mb-3", style={"height": "6px"}, animated=True, striped=True),
        html.Div(id="upload-results-display"),
    ]
)


@callback(
    Output("upload-page-browser-warning", "children"),
    Input("retailer-name-input", "id"),  # fires once per page load, cheap trigger
)
def show_in_app_browser_warning(_):
    app_name = detect_in_app_browser(request.headers.get("User-Agent", ""))
    if not app_name:
        return ""
    return dbc.Alert(
        [
            html.Strong("Uploads will not work in this browser. "),
            f"{app_name}'s built-in browser blocks photo uploads after you take/select a picture - "
            "this is a bug in that app, not this one. Tap the ⋮ menu or share icon at the top of your "
            "screen and choose \"Open in Chrome\" or \"Open in Safari\" before uploading.",
        ],
        color="danger",
        className="mb-3",
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
    Output("upload-pending", "data", allow_duplicate=True),
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
    return queue, len(queue), [], []


@callback(
    Output("upload-queue", "data", allow_duplicate=True),
    Output("upload-total", "data", allow_duplicate=True),
    Output("upload-results", "data", allow_duplicate=True),
    Output("upload-pending", "data", allow_duplicate=True),
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
    return queue, len(queue), [], []


def _result_to_alert(result: dict):
    kind = result.get("kind")
    filename = result.get("filename", "")
    if kind == "processing":
        return dbc.Alert(f"⏳ {filename}: uploaded, processing in the background...", color="light")
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
        f"✅ {filename}: {result['rows_found']} X-marked row(s) found.",
        color="success",
    )


@callback(
    Output("upload-queue", "data", allow_duplicate=True),
    Output("upload-results", "data", allow_duplicate=True),
    Output("upload-pending", "data", allow_duplicate=True),
    Output("upload-poll", "disabled", allow_duplicate=True),
    Output("upload-progress-text", "children"),
    Output("upload-progress-bar", "value"),
    Input("upload-queue", "data"),
    State("upload-results", "data"),
    State("upload-pending", "data"),
    State("upload-total", "data"),
    State("retailer-name-input", "value"),
    prevent_initial_call=True,
)
def process_next_in_queue(queue, results, pending, total, retailer_name):
    # Self-chaining on purpose: this callback's own Input is the Store it
    # writes to. Writing a shorter queue is what triggers the NEXT run - not
    # a fixed timer - so there is never more than one of these in flight at
    # once. This step itself is now FAST regardless of queue size: the slow
    # Groq work happens in a background thread (see services/processor.py),
    # so this only ever does local dedup/quality checks per file.
    queue = queue or []
    results = results or []
    pending = pending or []
    if not queue:
        return dash.no_update, dash.no_update, dash.no_update, dash.no_update, dash.no_update, dash.no_update

    item = queue[0]
    remaining = queue[1:]
    filename = item["filename"]
    current_user = session.get("username", "")

    try:
        _, content_string = item["content"].split(",", 1)
        saved_path = _save_uploaded_file(filename, content_string)
        summary = process_upload(
            saved_path,
            retailer_name=(retailer_name or "").strip(),
            uploaded_by=current_user,
        )
        for dup in summary["duplicates"]:
            results.append({"kind": "duplicate", "filename": filename, "duplicate": dup})
        for msg in summary["quality_rejects"]:
            results.append({"kind": "quality_reject", "filename": filename, "message": msg})
        for err in summary["errors"]:
            results.append({"kind": "partial_error", "filename": filename, "message": err})
        for q in summary["queued"]:
            results.append({"kind": "processing", "filename": filename, "image_id": q["image_id"]})
            pending.append({"image_id": q["image_id"], "filename": filename})
    except Exception as e:
        results.append({"kind": "error", "filename": filename, "message": str(e)})

    done_count = total - len(remaining)
    progress_text = f"Uploading {done_count} of {total}..." if remaining else f"All {total} file(s) uploaded - background processing continues below."
    progress_val = int((done_count / total) * 100) if total else 100
    poll_disabled = len(pending) == 0
    return remaining, results, pending, poll_disabled, progress_text, progress_val


@callback(
    Output("upload-results", "data", allow_duplicate=True),
    Output("upload-pending", "data", allow_duplicate=True),
    Output("upload-poll", "disabled", allow_duplicate=True),
    Input("upload-poll", "n_intervals"),
    State("upload-results", "data"),
    State("upload-pending", "data"),
    prevent_initial_call=True,
)
def poll_pending_results(_, results, pending):
    # Cheap on purpose: each tick is just a DB status read per pending
    # image_id, never the actual extraction work - safe to run on a timer
    # no matter how long the background processing takes.
    results = results or []
    pending = pending or []
    if not pending:
        return dash.no_update, dash.no_update, True

    still_pending = []
    for p in pending:
        status = get_image_status(p["image_id"])
        if status is None or status["status"] == "processing":
            still_pending.append(p)
            continue
        # Find and replace this image's placeholder "processing" result entry.
        for r in results:
            if r.get("kind") == "processing" and r.get("image_id") == p["image_id"]:
                if status["status"] == "done":
                    if status["error_message"]:
                        r["kind"] = "partial_error"
                        r["message"] = status["error_message"]
                    else:
                        r["kind"] = "success"
                        r["rows_found"] = status["rows_found"]
                else:  # failed
                    r["kind"] = "error"
                    r["message"] = status["error_message"] or "Processing failed."
                break

    return results, still_pending, len(still_pending) == 0


@callback(
    Output("upload-results-display", "children"),
    Input("upload-results", "data"),
)
def render_results(results):
    if not results:
        return ""
    return [_result_to_alert(r) for r in reversed(results)]
