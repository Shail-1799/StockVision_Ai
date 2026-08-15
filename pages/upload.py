import base64
import datetime as dt

import dash
from dash import html, dcc, callback, Output, Input, State
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
                            ["🖼️", html.Br(), "Upload from Gallery / Files"],
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
            "On your phone, 'Take Photo' opens the camera directly. Multiple images and "
            "PDFs at once are supported through 'Upload from Gallery / Files'.",
            className="text-muted small",
        ),
        dbc.Spinner(html.Div(id="upload-status"), color="primary"),
        html.Div(id="upload-results", className="mt-3"),
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


def _process_batch(contents_list, filenames_list, retailer_name):
    # Leave blank as-is - process_upload() auto-extracts the retailer from
    # each sheet when nothing is typed here; a typed value acts as an override.
    retailer_name = (retailer_name or "").strip()
    results = []
    for content, filename in zip(contents_list, filenames_list):
        _, content_string = content.split(",", 1)
        saved_path = _save_uploaded_file(filename, content_string)
        try:
            summary = process_upload(saved_path, retailer_name=retailer_name)
            if summary["errors"]:
                results.append(
                    dbc.Alert(
                        f"⚠️ {filename}: processed with errors - {'; '.join(summary['errors'])}",
                        color="warning",
                    )
                )
            else:
                results.append(
                    dbc.Alert(
                        f"✅ {filename}: {summary['rows_found']} X-marked row(s) found "
                        f"across {summary['images_created']} page(s).",
                        color="success",
                    )
                )
        except Exception as e:
            results.append(dbc.Alert(f"❌ {filename}: failed - {e}", color="danger"))
    return results


@callback(
    Output("upload-results", "children", allow_duplicate=True),
    Output("upload-status", "children", allow_duplicate=True),
    Input("upload-camera", "contents"),
    State("upload-camera", "filename"),
    State("retailer-name-input", "value"),
    prevent_initial_call=True,
)
def handle_camera_upload(contents, filename, retailer_name):
    if not contents:
        return dash.no_update, ""
    results = _process_batch([contents], [filename], retailer_name)
    return results, ""


@callback(
    Output("upload-results", "children", allow_duplicate=True),
    Output("upload-status", "children", allow_duplicate=True),
    Input("upload-files", "contents"),
    State("upload-files", "filename"),
    State("retailer-name-input", "value"),
    prevent_initial_call=True,
)
def handle_gallery_upload(list_of_contents, list_of_filenames, retailer_name):
    if not list_of_contents:
        return dash.no_update, ""
    results = _process_batch(list_of_contents, list_of_filenames, retailer_name)
    return results, ""
