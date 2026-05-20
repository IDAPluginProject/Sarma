"""Workflow DAG visualization for the code-audit subagent pipeline.

Shows a directed graph with the **Orchestrator** at the top and five
specialist subagents below: ``recon``, ``decompile``, ``vuln_hunt``,
``cross_ref``, ``reporter``. Each node renders status (idle / running /
done / failed) with colour + a soft pulsing animation while running.

The view is driven by ``StreamEvent`` payloads forwarded from the chat
page:

* ``subagent_start``    — flips a node to ``running``.
* ``subagent_complete`` — flips that node's most recent ``running`` instance
  to ``done`` (matched on ``tool_call_id``).
* ``subagent_error``    — same, but ``failed``.
* ``tool_start`` / ``tool_result`` / ``tool_error`` — recorded as activity
  rows scoped to the most recently-active subagent (or "orchestrator" when
  no subagent is currently running).
* ``run_started``       — full reset.
* ``run_completed``     — orchestrator → done.

No business logic beyond status book-keeping lives here — the visualization
is intentionally a passive renderer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from PySide6.QtCore import (
    QEasingCurve,
    QPointF,
    QPropertyAnimation,
    QRectF,
    Qt,
    Signal,
)
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QPainter,
    QPainterPath,
    QPen,
)
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsItem,
    QGraphicsObject,
    QGraphicsPathItem,
    QGraphicsScene,
    QGraphicsView,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from app.chat.audit_subagents import AUDIT_SUBAGENT_ORDER

if TYPE_CHECKING:
    from app.i18n import I18n


# ---------------------------------------------------------------------------
# Status helpers
# ---------------------------------------------------------------------------

STATUS_IDLE = "idle"
STATUS_RUNNING = "running"
STATUS_DONE = "done"
STATUS_FAILED = "failed"

_STATUS_COLORS_LIGHT: dict[str, tuple[str, str, str]] = {
    # status -> (fill, border, text)
    STATUS_IDLE:    ("#f3f4f6", "#cbd5e1", "#475569"),
    STATUS_RUNNING: ("#dbeafe", "#3b82f6", "#1e40af"),
    STATUS_DONE:    ("#dcfce7", "#16a34a", "#166534"),
    STATUS_FAILED:  ("#fee2e2", "#dc2626", "#991b1b"),
}

_STATUS_COLORS_DARK: dict[str, tuple[str, str, str]] = {
    STATUS_IDLE:    ("#262a37", "#3a4154", "#9aa3b2"),
    STATUS_RUNNING: ("#1d3557", "#60a5fa", "#bfdbfe"),
    STATUS_DONE:    ("#14532d", "#4ade80", "#bbf7d0"),
    STATUS_FAILED:  ("#7f1d1d", "#f87171", "#fecaca"),
}


def _status_colors(status: str) -> tuple[str, str, str]:
    from app.ui.theme import current_theme_mode

    table = (
        _STATUS_COLORS_DARK
        if current_theme_mode() == "dark"
        else _STATUS_COLORS_LIGHT
    )
    return table.get(status, table[STATUS_IDLE])


# ---------------------------------------------------------------------------
# Graphics items
# ---------------------------------------------------------------------------

# Localized labels populated lazily on first widget construction so the
# strings can be retranslated.  Keys mirror AUDIT_SUBAGENT_ORDER plus
# "orchestrator".
_DEFAULT_LABELS = {
    "orchestrator": "Orchestrator",
    "recon": "Recon",
    "hunt": "Hunt",
    "validate": "Validate",
    "gapfill": "Gapfill",
    "dedupe": "Dedupe",
    "trace": "Trace",
    "feedback": "Feedback",
    "report": "Report",
}


class _AgentNode(QGraphicsObject):
    """A single node in the workflow graph.

    QGraphicsObject (not QGraphicsItem) so it can own a QPropertyAnimation
    bound to a Qt property — we animate ``pulse`` while ``running``.
    """

    NODE_WIDTH = 160
    NODE_HEIGHT = 68

    clicked = Signal(str)  # node id

    def __init__(
        self,
        node_id: str,
        label: str,
        parent: QGraphicsItem | None = None,
    ) -> None:
        super().__init__(parent)
        self._node_id = node_id
        self._label = label
        self._status = STATUS_IDLE
        self._pulse = 0.0
        self._tool_count = 0
        self._description: str = ""

        self.setAcceptHoverEvents(True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, False)

        # Pulse animation (idle until set_status(running) triggers it).
        self._anim = QPropertyAnimation(self, b"pulse")
        self._anim.setDuration(1100)
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.setEasingCurve(QEasingCurve.Type.InOutSine)
        self._anim.setLoopCount(-1)

    # ---- Qt graphics API ----

    def boundingRect(self) -> QRectF:  # type: ignore[override]
        # Add a few px so the running halo doesn't clip.
        return QRectF(
            -self.NODE_WIDTH / 2 - 6,
            -self.NODE_HEIGHT / 2 - 6,
            self.NODE_WIDTH + 12,
            self.NODE_HEIGHT + 12,
        )

    def paint(self, painter: QPainter, option, widget=None) -> None:  # type: ignore[override]
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        fill, border, text = _status_colors(self._status)

        rect = QRectF(
            -self.NODE_WIDTH / 2,
            -self.NODE_HEIGHT / 2,
            self.NODE_WIDTH,
            self.NODE_HEIGHT,
        )

        # Pulsing halo while running.
        if self._status == STATUS_RUNNING and self._pulse > 0:
            halo_color = QColor(border)
            halo_color.setAlpha(int(60 * (1.0 - self._pulse)))
            halo_pen = QPen(halo_color, 2 + 6 * self._pulse)
            painter.setPen(halo_pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(
                rect.adjusted(-3 * self._pulse, -3 * self._pulse,
                              3 * self._pulse, 3 * self._pulse),
                12, 12,
            )

        painter.setPen(QPen(QColor(border), 1.5))
        painter.setBrush(QBrush(QColor(fill)))
        painter.drawRoundedRect(rect, 10, 10)

        # Label
        painter.setPen(QPen(QColor(text)))
        font = QFont()
        font.setPointSize(11)
        font.setBold(True)
        painter.setFont(font)
        label_rect = QRectF(rect.left(), rect.top() + 8, rect.width(), 24)
        painter.drawText(
            label_rect,
            int(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop),
            self._label,
        )

        # Status icon + tool count
        font.setPointSize(9)
        font.setBold(False)
        painter.setFont(font)
        meta = f"{_status_glyph(self._status)}  {self._status}"
        if self._tool_count:
            meta += f"  ·  {self._tool_count} tool"
            if self._tool_count > 1:
                meta += "s"
        meta_rect = QRectF(rect.left(), rect.top() + 34, rect.width(), 20)
        painter.drawText(
            meta_rect,
            int(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop),
            meta,
        )

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self._node_id)
        super().mousePressEvent(event)

    # ---- Properties ----

    def get_pulse(self) -> float:
        return self._pulse

    def set_pulse(self, value: float) -> None:
        self._pulse = value
        self.update()

    pulse = property(get_pulse, set_pulse)

    # ---- Public API ----

    @property
    def node_id(self) -> str:
        return self._node_id

    @property
    def status(self) -> str:
        return self._status

    def set_status(self, status: str) -> None:
        self._status = status
        if status == STATUS_RUNNING:
            if self._anim.state() != QPropertyAnimation.State.Running:
                self._anim.start()
        else:
            if self._anim.state() == QPropertyAnimation.State.Running:
                self._anim.stop()
            self._pulse = 0.0
        self.update()

    def increment_tool_count(self) -> None:
        self._tool_count += 1
        self.update()

    def reset(self) -> None:
        self._status = STATUS_IDLE
        self._tool_count = 0
        self._description = ""
        if self._anim.state() == QPropertyAnimation.State.Running:
            self._anim.stop()
        self._pulse = 0.0
        self.update()


def _status_glyph(status: str) -> str:
    return {
        STATUS_IDLE:    "○",
        STATUS_RUNNING: "◉",
        STATUS_DONE:    "✓",
        STATUS_FAILED:  "✗",
    }.get(status, "○")


# ---------------------------------------------------------------------------
# Edges
# ---------------------------------------------------------------------------

class _Edge(QGraphicsPathItem):
    """Curved arrow from one node to another. Repaints on theme change."""

    def __init__(
        self,
        src: _AgentNode,
        dst: _AgentNode,
        parent: QGraphicsItem | None = None,
        dashed: bool = False,
        horizontal: bool = False,
    ) -> None:
        super().__init__(parent)
        self._src = src
        self._dst = dst
        self._dashed = dashed
        self._horizontal = horizontal
        self.setZValue(-1)
        self._refresh_pen()
        self._build_path()

    def _refresh_pen(self) -> None:
        from app.ui.theme import current_palette

        c = current_palette()
        style = Qt.PenStyle.DashLine if self._dashed else Qt.PenStyle.SolidLine
        pen = QPen(QColor(c.border), 1.2, style)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        self.setPen(pen)

    def _build_path(self) -> None:
        a = self._src.pos()
        b = self._dst.pos()

        if self._horizontal:
            # Horizontal edge: right side of src → left side of dst
            start = QPointF(a.x() + _AgentNode.NODE_WIDTH / 2, a.y())
            end = QPointF(b.x() - _AgentNode.NODE_WIDTH / 2, b.y())
            path = QPainterPath(start)
            mid_x = (start.x() + end.x()) / 2
            c1 = QPointF(mid_x, start.y())
            c2 = QPointF(mid_x, end.y())
            path.cubicTo(c1, c2, end)
        else:
            # Vertical edge: bottom of src → top of dst
            start = QPointF(a.x(), a.y() + _AgentNode.NODE_HEIGHT / 2)
            end = QPointF(b.x(), b.y() - _AgentNode.NODE_HEIGHT / 2)
            path = QPainterPath(start)
            mid_y = (start.y() + end.y()) / 2
            c1 = QPointF(start.x(), mid_y)
            c2 = QPointF(end.x(), mid_y)
            path.cubicTo(c1, c2, end)

        self.setPath(path)


# ---------------------------------------------------------------------------
# Activity panel
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class _Activity:
    subagent: str
    summary: str
    detail: str = ""
    status: str = "running"  # running / done / failed
    tool_name: str = ""


class _ActivityList(QWidget):
    """Compact scrollable list of recent activities (tool calls) per subagent."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("workflowActivityList")
        # Inherit the panel background so the area never falls back to the
        # OS-default dark window colour when no cards are present.
        self.setAutoFillBackground(True)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._rows: list[QFrame] = []

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self._container = QWidget()
        self._container.setObjectName("workflowActivityContainer")
        self._container.setAttribute(
            Qt.WidgetAttribute.WA_StyledBackground, True
        )
        self._list_layout = QVBoxLayout(self._container)
        self._list_layout.setContentsMargins(0, 4, 0, 4)
        self._list_layout.setSpacing(2)
        self._list_layout.addStretch(1)

        scroll = QScrollArea()
        scroll.setObjectName("workflowActivityScroll")
        scroll.setWidget(self._container)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        # QScrollArea has an inner viewport widget that ignores QSS unless we
        # mark it as a styled background; otherwise it shows the dark default
        # palette on Windows.
        scroll.viewport().setAutoFillBackground(False)
        outer.addWidget(scroll, 1)

    def add(self, activity: _Activity) -> QFrame:
        card = QFrame()
        card.setObjectName("workflowActivityCard")
        v = QVBoxLayout(card)
        v.setContentsMargins(8, 6, 8, 6)
        v.setSpacing(2)

        title = QLabel(f"[{activity.subagent}] {activity.summary}")
        title.setObjectName("workflowActivityTitle")
        title.setWordWrap(True)
        v.addWidget(title)

        if activity.detail:
            detail = QLabel(activity.detail)
            detail.setObjectName("workflowActivityDetail")
            detail.setWordWrap(True)
            v.addWidget(detail)

        # Insert at top (chronological recency at top).
        self._list_layout.insertWidget(0, card)
        self._rows.append(card)

        # Cap to ~80 rows to avoid unbounded growth.
        if len(self._rows) > 80:
            old = self._rows.pop(0)
            self._list_layout.removeWidget(old)
            old.deleteLater()
        return card

    def clear(self) -> None:
        while self._rows:
            row = self._rows.pop()
            self._list_layout.removeWidget(row)
            row.deleteLater()


# ---------------------------------------------------------------------------
# Workflow panel
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class _SubagentRunState:
    name: str
    tool_call_id: str
    description: str = ""
    started_idx: int = 0  # order of start, for picking the "latest running"


class WorkflowDagView(QWidget):
    """Graphical workflow visualization driven by chat stream events.

    Public API:
      * ``begin_run()``        — reset all nodes for a fresh user turn.
      * ``end_run(failed)``    — orchestrator -> done/failed.
      * ``handle_event(dict)`` — dispatches on ``StreamEvent.type``.
    """

    def __init__(
        self,
        i18n: "I18n | None" = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("workflowPanel")
        self._i18n = i18n

        # tool_call_id -> running subagent state.  Used to map completion
        # events (which only carry tool_call_id) back to a node id.
        self._pending: dict[str, _SubagentRunState] = {}
        # Track the "currently active" subagent for routing tool_* events.
        self._active_subagent: str | None = None
        self._start_counter = 0

        self._build_ui()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        title = QLabel(self._t("chat.workflow.title", default="Workflow"))
        title.setObjectName("workflowTitle")
        outer.addWidget(title)

        # --- Graphics scene fills the remaining panel width ---
        self._scene = QGraphicsScene(self)
        self._view = QGraphicsView(self._scene)
        self._view.setObjectName("workflowGraphView")
        self._view.setRenderHint(QPainter.RenderHint.Antialiasing)
        self._view.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self._view.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self._view.setFrameShape(QFrame.Shape.NoFrame)
        self._view.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )

        self._nodes: dict[str, _AgentNode] = {}
        self._build_graph()
        outer.addWidget(self._view, 1)

        # Activity is rendered inline in the chat message list (tool traces)
        # so the workflow panel can devote its full width to the DAG.  We
        # keep a hidden _ActivityList instance so handle_event() does not
        # need to branch on its presence.
        self._activity = _ActivityList()
        self._activity.hide()

    def attach_activity_list(self, activity: _ActivityList) -> None:
        """Replace the internal (hidden) activity list with an external one.

        After calling this, ``handle_event()`` routes all activity rows to
        the external widget instead.
        """
        self._activity = activity

    def _build_graph(self) -> None:
        """Build the vulnerability discovery harness DAG.

        Layout:
          Orchestrator (top center, y=-120)
                |
          Recon → Hunt → Validate → Dedupe → Trace → Feedback → Report
                          ↕
                       Gapfill (below, y=+120)
                          ↑ (dashed from Feedback)
        """
        labels = self._localized_labels()

        # Main pipeline (linear, left to right at y=0)
        main_stages = ["recon", "hunt", "validate", "dedupe", "trace", "feedback", "report"]
        gap = _AgentNode.NODE_WIDTH + 20
        count = len(main_stages)
        x_offset = -(count - 1) * gap / 2

        for i, name in enumerate(main_stages):
            node = _AgentNode(name, labels.get(name, name))
            self._scene.addItem(node)
            self._nodes[name] = node
            node.setPos(x_offset + i * gap, 0)

        # Linear edges: Recon→Hunt→Validate→Dedupe→Trace→Feedback→Report
        for i in range(len(main_stages) - 1):
            src = self._nodes[main_stages[i]]
            dst = self._nodes[main_stages[i + 1]]
            self._scene.addItem(_Edge(src, dst, horizontal=True))

        # Orchestrator at top, arrow down to Recon
        orch = _AgentNode("orchestrator", labels.get("orchestrator", "Orchestrator"))
        self._scene.addItem(orch)
        self._nodes["orchestrator"] = orch
        recon_x = self._nodes["recon"].pos().x()
        orch.setPos(recon_x, -130)
        self._scene.addItem(_Edge(orch, self._nodes["recon"]))

        # Gapfill below, centered between Hunt and Validate
        hunt_x = self._nodes["hunt"].pos().x()
        validate_x = self._nodes["validate"].pos().x()
        gapfill_x = (hunt_x + validate_x) / 2
        gapfill = _AgentNode("gapfill", labels.get("gapfill", "Gapfill"))
        self._scene.addItem(gapfill)
        self._nodes["gapfill"] = gapfill
        gapfill.setPos(gapfill_x, 130)

        # Dashed edges: Hunt↔Gapfill, Validate↔Gapfill
        self._scene.addItem(_Edge(self._nodes["hunt"], gapfill, dashed=True))
        self._scene.addItem(_Edge(gapfill, self._nodes["hunt"], dashed=True))
        self._scene.addItem(_Edge(self._nodes["validate"], gapfill, dashed=True))
        self._scene.addItem(_Edge(gapfill, self._nodes["validate"], dashed=True))

        # Dashed edge: Feedback → Gapfill
        self._scene.addItem(_Edge(self._nodes["feedback"], gapfill, dashed=True))

        # Fit scene
        margin = 40
        rect = self._scene.itemsBoundingRect().adjusted(
            -margin, -margin, margin, margin
        )
        self._scene.setSceneRect(rect)

    def _localized_labels(self) -> dict[str, str]:
        if self._i18n is None:
            return dict(_DEFAULT_LABELS)
        out: dict[str, str] = {}
        for key, fallback in _DEFAULT_LABELS.items():
            i18n_key = f"chat.workflow.node.{key}"
            value = self._i18n.t(i18n_key)
            out[key] = fallback if value == i18n_key else value
        return out

    def _t(self, key: str, default: str = "", **kwargs) -> str:
        if self._i18n is None:
            return default or key
        try:
            text = self._i18n.t(key, **kwargs)
        except Exception:
            return default or key
        # i18n.t falls back to the bare key when no translation exists.
        # In that case prefer the explicit English fallback the caller passed.
        if text == key and default:
            return default
        return text

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        # Scale to fill width; let height be determined by content.
        scene_rect = self._scene.sceneRect()
        if scene_rect.width() <= 0:
            return
        view_width = self._view.viewport().width()
        scale = view_width / scene_rect.width()
        self._view.resetTransform()
        self._view.scale(scale, scale)
        self._view.centerOn(scene_rect.center())

    # ------------------------------------------------------------------
    # Public event API
    # ------------------------------------------------------------------

    def begin_run(self) -> None:
        for node in self._nodes.values():
            node.reset()
        self._pending.clear()
        self._active_subagent = None
        self._start_counter = 0
        self._activity.clear()
        self._nodes["orchestrator"].set_status(STATUS_RUNNING)

    def end_run(self, failed: bool = False) -> None:
        orch = self._nodes["orchestrator"]
        orch.set_status(STATUS_FAILED if failed else STATUS_DONE)
        # Any subagent left "running" is downgraded to its final state.
        for state in list(self._pending.values()):
            node = self._nodes.get(state.name)
            if node and node.status == STATUS_RUNNING:
                node.set_status(STATUS_FAILED if failed else STATUS_DONE)
        self._pending.clear()
        self._active_subagent = None

    def handle_event(self, event: dict) -> None:
        et = event.get("type", "")
        payload = event.get("payload", {}) or {}

        if et == "run_started":
            self.begin_run()
        elif et == "run_completed":
            self.end_run(failed=False)
        elif et == "run_failed":
            self.end_run(failed=True)
        elif et == "subagent_start":
            self._on_subagent_start(payload)
        elif et == "subagent_complete":
            self._on_subagent_finish(payload, failed=False)
        elif et == "subagent_error":
            self._on_subagent_finish(payload, failed=True)
        elif et == "tool_start":
            self._on_tool_start(payload)
        elif et == "tool_result":
            self._on_tool_result(payload, failed=False)
        elif et == "tool_error":
            self._on_tool_result(payload, failed=True)
        elif et == "skill_triggered":
            self._on_skill_triggered(payload)

    # ------------------------------------------------------------------
    # Internal event handlers
    # ------------------------------------------------------------------

    def _on_subagent_start(self, payload: dict) -> None:
        name = payload.get("subagent", "")
        node = self._nodes.get(name)
        if node is None:
            return
        node.set_status(STATUS_RUNNING)
        self._start_counter += 1
        tool_call_id = payload.get("tool_call_id", "")
        self._pending[tool_call_id] = _SubagentRunState(
            name=name,
            tool_call_id=tool_call_id,
            description=payload.get("description", ""),
            started_idx=self._start_counter,
        )
        self._active_subagent = name
        self._activity.add(_Activity(
            subagent=name,
            summary="dispatched",
            detail=payload.get("description", "")[:200],
        ))

    def _on_subagent_finish(self, payload: dict, failed: bool) -> None:
        tool_call_id = payload.get("tool_call_id", "")
        state = self._pending.pop(tool_call_id, None)
        if state is None:
            return
        node = self._nodes.get(state.name)
        if node:
            node.set_status(STATUS_FAILED if failed else STATUS_DONE)
        # If the just-finished subagent was the "active" one, fall back to
        # the next most-recently-started still-running one (or None).
        if self._active_subagent == state.name:
            self._active_subagent = self._pick_active_subagent()
        self._activity.add(_Activity(
            subagent=state.name,
            summary="failed" if failed else "complete",
            detail=(payload.get("error") or payload.get("result") or "")[:200],
            status="failed" if failed else "done",
        ))

    def _on_tool_start(self, payload: dict) -> None:
        tool_name = payload.get("tool_name", "")
        # Suppress the meta-tool — it's already represented as subagent_start.
        if tool_name == "task":
            return
        target = self._active_subagent or "orchestrator"
        node = self._nodes.get(target)
        if node is not None:
            node.increment_tool_count()
        self._activity.add(_Activity(
            subagent=target,
            summary=tool_name or "tool",
            detail=_short_args(payload.get("args")),
            status="running",
            tool_name=tool_name,
        ))

    def _on_tool_result(self, payload: dict, failed: bool) -> None:
        tool_name = payload.get("tool_name", "")
        if tool_name == "task":
            return
        target = self._active_subagent or "orchestrator"
        self._activity.add(_Activity(
            subagent=target,
            summary=f"{tool_name} {'✗' if failed else '✓'}",
            detail=(payload.get("error") or payload.get("result") or "")[:200],
            status="failed" if failed else "done",
            tool_name=tool_name,
        ))

    def _on_skill_triggered(self, payload: dict) -> None:
        skill_name = payload.get("skill_name", "unknown")
        event = payload.get("event", "")
        target = payload.get("subagent") or self._active_subagent or "orchestrator"
        self._activity.add(_Activity(
            subagent=target,
            summary=f"⚡ skill: {skill_name}",
            detail=payload.get("detail", event)[:200],
            status="running",
            tool_name=f"skill:{skill_name}",
        ))

    def _pick_active_subagent(self) -> str | None:
        if not self._pending:
            return None
        # Highest started_idx == most-recently-started.
        latest = max(self._pending.values(), key=lambda s: s.started_idx)
        return latest.name


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _short_args(args) -> str:
    if not args:
        return ""
    try:
        import json
        text = json.dumps(args, ensure_ascii=False, sort_keys=True)
    except (TypeError, ValueError):
        text = str(args)
    if len(text) > 160:
        text = text[:157] + "..."
    return text
