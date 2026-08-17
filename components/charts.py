"""Shared Plotly styling so every chart in the app looks like one coherent
product instead of default plotly.express output. Import style_fig() and
call it last, after building the figure with px/go.
"""
import plotly.graph_objects as go

# A calmer, more deliberate palette than plotly's default rainbow - reused
# across every chart so retailers/products/statuses read consistently
# wherever they appear.
COLORWAY = [
    "#2c3e50",  # navy - primary
    "#18bc9c",  # teal - success/positive
    "#e74c3c",  # red - shortage/alert
    "#f39c12",  # amber - warning
    "#3498db",  # blue - secondary
    "#9b59b6",  # purple
    "#95a5a6",  # grey - muted/other
]

FONT_FAMILY = "'Segoe UI', system-ui, -apple-system, sans-serif"


def style_fig(fig: go.Figure, title: str = None, height: int = None) -> go.Figure:
    """Applies the shared look: transparent background (matches the card
    it sits in), consistent margins/fonts, muted gridlines, no chart border."""
    fig.update_layout(
        template="plotly_white",
        colorway=COLORWAY,
        font=dict(family=FONT_FAMILY, size=13, color="#2c3e50"),
        title=dict(text=title, font=dict(size=16, weight=600)) if title else None,
        margin=dict(t=50 if title else 20, b=30, l=40, r=20),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        hoverlabel=dict(bgcolor="white", font_size=13),
    )
    fig.update_xaxes(showgrid=False, showline=True, linecolor="#e0e0e0", zeroline=False)
    fig.update_yaxes(showgrid=True, gridcolor="#f0f2f5", showline=False, zeroline=False)
    if height:
        fig.update_layout(height=height)
    return fig


def empty_fig(message: str = "No data yet") -> go.Figure:
    fig = go.Figure()
    fig.add_annotation(
        text=message,
        xref="paper", yref="paper", x=0.5, y=0.5,
        showarrow=False, font=dict(size=14, color="#95a5a6"),
    )
    fig.update_xaxes(visible=False)
    fig.update_yaxes(visible=False)
    return style_fig(fig)
