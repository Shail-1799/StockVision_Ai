import shutil
from datetime import datetime

import dash
from dash import html, dcc, callback, Output, Input, State
import dash_bootstrap_components as dbc

import config
from database.db import get_setting, set_setting

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
                    dbc.Button("Save Thresholds", id="save-thresholds-btn", color="primary", className="mt-3"),
                    html.Div(id="save-thresholds-result", className="mt-2"),
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
    prevent_initial_call=True,
)
def save_thresholds(n_clicks, ocr_t, cross_t, fuzzy_t, regex):
    set_setting("ocr_confidence_threshold", ocr_t)
    set_setting("cross_confidence_threshold", cross_t)
    set_setting("fuzzy_match_threshold", fuzzy_t)
    set_setting("alias_regex", regex)
    return dbc.Alert("✅ Thresholds saved.", color="success", duration=3000)


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
