from __future__ import annotations

import json
import functools
import http.server
import socketserver
import threading
import time
import urllib.parse
from dataclasses import dataclass
from pathlib import Path


def write_web_report(report: dict, output_path: str | Path, live_data_path: str | Path | None = None) -> Path:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(to_web_payload(report), ensure_ascii=True)
    live_source = Path(live_data_path).name if live_data_path else None
    path.write_text(render_html(payload, live_source), encoding="utf-8")
    return path


def default_web_path(benchmark_path: str | Path) -> Path:
    path = Path(benchmark_path)
    return path.with_suffix(".html")


def default_live_data_path(web_path: str | Path) -> Path:
    path = Path(web_path)
    return path.with_suffix(".live.json")


def write_live_data(report: dict, output_path: str | Path) -> Path:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(to_web_payload(report), ensure_ascii=True, indent=2), encoding="utf-8")
    tmp_path.replace(path)
    return path


def serve_web_report(path: str | Path, port: int = 0) -> str:
    server = start_web_report_server(path, port)
    print(f"Web replay available at: {server.url}", flush=True)
    print("Press Ctrl-C to stop the web replay server.", flush=True)
    server.wait_until_interrupted()
    return server.url


def start_web_report_server(path: str | Path, port: int = 0) -> "WebReportServer":
    report_path = Path(path).resolve()
    handler = functools.partial(QuietHTTPRequestHandler, directory=str(report_path.parent))
    try:
        server = ReusableTCPServer(("127.0.0.1", port), handler)
    except OSError as error:
        if port:
            print(f"Could not use localhost:{port} ({error}). Choosing an open port instead.", flush=True)
            return start_web_report_server(report_path, 0)
        raise

    host, resolved_port = server.server_address
    url = web_report_url(report_path, resolved_port)
    thread = threading.Thread(target=server.serve_forever, name="llmcheesbench-web", daemon=True)
    thread.start()
    return WebReportServer(server, thread, url)


@dataclass
class WebReportServer:
    server: socketserver.TCPServer
    thread: threading.Thread
    url: str

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def wait_until_interrupted(self) -> None:
        try:
            while self.thread.is_alive():
                time.sleep(0.25)
        except KeyboardInterrupt:
            self.stop()
            print("\nStopped web replay server.", flush=True)


def web_report_url(path: str | Path, port: int) -> str:
    report_path = Path(path)
    return f"http://localhost:{port}/{urllib.parse.quote(report_path.name)}"


class ReusableTCPServer(socketserver.TCPServer):
    allow_reuse_address = True


class QuietHTTPRequestHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, format, *args):
        return


def to_web_payload(report: dict) -> dict:
    return {
        "benchmark": report.get("benchmark", "LLMCheesBench"),
        "status": report.get("status", "complete"),
        "model_name": report.get("model_name") or report.get("model") or "model",
        "generated_at": report.get("generated_at"),
        "engine": report.get("engine", {}),
        "summary": report.get("summary", {}),
        "total_positions": report.get("total_positions") or len(report.get("positions_requested", [])) or len(report.get("positions", [])),
        "completed_positions": report.get("completed_positions", len(report.get("positions", []))),
        "position_manifest": report.get("position_manifest", []),
        "positions": report.get("positions", []),
    }


def render_html(payload_json: str, live_source: str | None = None) -> str:
    live_source_json = json.dumps(live_source)
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>LLMCheesBench Replay</title>
  <style>
    :root {{
      color-scheme: light;
      --ink: #172026;
      --muted: #5f6b73;
      --line: #d7dce0;
      --paper: #f7f8f8;
      --panel: #ffffff;
      --light: #e9dec7;
      --dark: #6f8f72;
      --accent: #2f6fed;
      --engine: #bd7b19;
      --model: #237b64;
      --both: #2f6fed;
      --bad: #b94135;
      --wait: #7d8790;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      color: var(--ink);
      background: var(--paper);
    }}
    header {{
      display: flex;
      justify-content: space-between;
      align-items: end;
      gap: 24px;
      padding: 22px 28px;
      border-bottom: 1px solid var(--line);
      background: var(--panel);
    }}
    h1 {{
      margin: 0 0 4px;
      font-size: 24px;
      line-height: 1.1;
      letter-spacing: 0;
    }}
    .subtle {{ color: var(--muted); font-size: 14px; }}
    .status-line {{
      display: inline-flex;
      align-items: center;
      gap: 8px;
      min-height: 22px;
    }}
    .dot {{
      width: 8px;
      height: 8px;
      border-radius: 50%;
      background: var(--wait);
    }}
    .dot.running {{
      background: var(--accent);
      animation: pulse 1.1s ease-in-out infinite;
    }}
    @keyframes pulse {{
      0%, 100% {{ transform: scale(1); opacity: 0.65; }}
      50% {{ transform: scale(1.45); opacity: 1; }}
    }}
    main {{
      display: grid;
      grid-template-columns: minmax(300px, 560px) minmax(280px, 1fr);
      gap: 24px;
      padding: 24px 28px 32px;
      max-width: 1220px;
      margin: 0 auto;
    }}
    .board-wrap {{
      width: min(100%, 560px);
    }}
    .board {{
      position: relative;
      width: 100%;
      aspect-ratio: 1;
      display: grid;
      grid-template-columns: repeat(8, 1fr);
      border: 1px solid #24302b;
      background: #24302b;
    }}
    .square {{
      position: relative;
      display: grid;
      place-items: center;
      min-width: 0;
      min-height: 0;
      font-size: clamp(24px, 7vw, 54px);
      line-height: 1;
      user-select: none;
    }}
    .light {{ background: var(--light); }}
    .dark {{ background: var(--dark); }}
    .coord {{
      position: absolute;
      left: 5px;
      bottom: 4px;
      font-size: 11px;
      line-height: 1;
      color: rgba(23, 32, 38, 0.68);
    }}
    .from.model, .to.model {{ box-shadow: inset 0 0 0 4px var(--model); }}
    .from.engine, .to.engine {{ box-shadow: inset 0 0 0 4px var(--engine); }}
    .from.both, .to.both {{ box-shadow: inset 0 0 0 4px var(--both); }}
    .square.split-model-engine::before {{
      content: "";
      position: absolute;
      inset: 0;
      background: linear-gradient(135deg, rgba(35,123,100,.34) 0 50%, rgba(189,123,25,.38) 50% 100%);
      pointer-events: none;
    }}
    .tag {{
      position: absolute;
      top: 4px;
      right: 4px;
      border-radius: 4px;
      padding: 2px 4px;
      color: white;
      font-size: 10px;
      font-weight: 700;
      line-height: 1;
    }}
    .tag.model {{ background: var(--model); }}
    .tag.engine {{ background: var(--engine); }}
    .tag.both {{ background: var(--both); }}
    .arrow-layer {{
      position: absolute;
      inset: 0;
      width: 100%;
      height: 100%;
      pointer-events: none;
      overflow: visible;
    }}
    .piece {{
      transition: transform 180ms ease, opacity 180ms ease;
      text-shadow: 0 1px 0 rgba(255,255,255,.35);
    }}
    .controls, .details, .list {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
    }}
    .controls {{ padding: 14px; margin-top: 14px; }}
    .row {{ display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }}
    button, select {{
      height: 36px;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: #fff;
      color: var(--ink);
      padding: 0 12px;
      font: inherit;
      font-size: 14px;
    }}
    button {{ cursor: pointer; }}
    button.primary {{ background: var(--accent); color: #fff; border-color: var(--accent); }}
    button.model {{ background: var(--model); color: #fff; border-color: var(--model); }}
    button.engine {{ background: var(--engine); color: #fff; border-color: var(--engine); }}
    button.both {{ background: var(--both); color: #fff; border-color: var(--both); }}
    button:disabled {{ opacity: 0.45; cursor: not-allowed; }}
    select {{ flex: 1 1 260px; min-width: 0; }}
    .side {{ display: grid; gap: 16px; align-content: start; }}
    .details {{ padding: 18px; }}
    .details h2 {{ margin: 0 0 6px; font-size: 20px; letter-spacing: 0; }}
    .metrics {{
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 10px;
      margin: 16px 0;
    }}
    .metric {{
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 10px;
      background: #fbfbfb;
    }}
    .metric b {{ display: block; font-size: 18px; }}
    .metric span {{ color: var(--muted); font-size: 12px; }}
    .moves {{
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 10px;
      margin: 14px 0;
    }}
    .move-box {{
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 10px;
      min-height: 82px;
    }}
    .move-box.model {{ border-top: 4px solid var(--model); }}
    .move-box.engine {{ border-top: 4px solid var(--engine); }}
    .move-note {{
      margin-top: 4px;
      color: var(--muted);
      font-size: 12px;
      line-height: 1.35;
    }}
    .label {{ color: var(--muted); font-size: 12px; text-transform: uppercase; }}
    .move-text {{ margin-top: 4px; font-size: 18px; font-weight: 700; }}
    pre {{
      white-space: pre-wrap;
      overflow-wrap: anywhere;
      max-height: 160px;
      overflow: auto;
      padding: 10px;
      background: #f0f2f3;
      border-radius: 6px;
      font-size: 12px;
      line-height: 1.35;
    }}
    .list {{ overflow: hidden; }}
    .list button {{
      width: 100%;
      height: auto;
      min-height: 42px;
      border: 0;
      border-bottom: 1px solid var(--line);
      border-radius: 0;
      display: flex;
      justify-content: space-between;
      gap: 12px;
      text-align: left;
    }}
    .list button.active {{ background: #e9f0ff; }}
    .pill {{
      flex: 0 0 auto;
      border-radius: 999px;
      padding: 2px 8px;
      font-size: 12px;
      color: #fff;
      background: var(--bad);
    }}
    .pill.ok {{ background: var(--model); }}
    .pill.waiting {{ background: var(--wait); }}
    .legend {{
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      margin-top: 10px;
      color: var(--muted);
      font-size: 13px;
    }}
    .legend span {{ display: inline-flex; align-items: center; gap: 6px; }}
    .swatch {{
      width: 12px;
      height: 12px;
      border-radius: 3px;
      display: inline-block;
    }}
    .swatch.model {{ background: var(--model); }}
    .swatch.engine {{ background: var(--engine); }}
    .swatch.both {{ background: var(--both); }}
    .waiting-panel {{
      border: 1px dashed var(--line);
      border-radius: 6px;
      padding: 12px;
      color: var(--muted);
      background: #fbfbfb;
      line-height: 1.4;
    }}
    @media (max-width: 860px) {{
      header {{ align-items: start; flex-direction: column; }}
      main {{ grid-template-columns: 1fr; padding: 16px; }}
      .metrics, .moves {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>
  <header>
    <div>
      <h1>LLMCheesBench Replay</h1>
      <div class="subtle status-line"><span class="dot" id="statusDot"></span><span id="runMeta"></span></div>
    </div>
    <div class="subtle" id="engineMeta"></div>
  </header>
  <main>
    <section>
      <div class="board-wrap">
        <div class="board" id="board"></div>
      </div>
      <div class="controls">
        <div class="row">
          <button id="prevBtn" title="Previous position">Prev</button>
          <select id="positionSelect" aria-label="Position"></select>
          <button id="nextBtn" title="Next position">Next</button>
        </div>
        <div class="row" style="margin-top:10px">
          <button class="model" id="modelBtn">Show Model Move</button>
          <button class="engine" id="engineBtn">Show Stockfish Move</button>
          <button class="both" id="bothBtn">Compare Both</button>
          <button class="primary" id="resetBtn">Reset Board</button>
        </div>
        <div class="legend">
          <span><i class="swatch model"></i>LLM</span>
          <span><i class="swatch engine"></i>Master AI</span>
          <span><i class="swatch both"></i>Same move</span>
        </div>
      </div>
    </section>
    <section class="side">
      <div class="details">
        <h2 id="positionTitle"></h2>
        <div class="subtle" id="positionSubtitle"></div>
        <div class="metrics">
          <div class="metric"><b id="scoreMetric"></b><span>Score</span></div>
          <div class="metric"><b id="lossMetric"></b><span>Centipawn Loss</span></div>
          <div class="metric"><b id="matchMetric"></b><span>Engine Match</span></div>
        </div>
        <div class="moves">
          <div class="move-box model">
            <div class="label">Model</div>
            <div class="move-text" id="modelMove"></div>
            <div class="move-note" id="modelNote"></div>
          </div>
          <div class="move-box engine">
            <div class="label">Master AI</div>
            <div class="move-text" id="engineMove"></div>
            <div class="move-note" id="engineNote"></div>
          </div>
        </div>
        <div class="waiting-panel" id="waitingPanel" hidden>Waiting for this benchmark position to finish. The page refreshes automatically as more LLM moves arrive.</div>
        <div class="label">Model Response</div>
        <pre id="responseText"></pre>
      </div>
      <div class="list" id="positionList"></div>
    </section>
  </main>
  <script>
    let data = {payload_json};
    const liveSource = {live_source_json};
    const files = ['a','b','c','d','e','f','g','h'];
    const unicodePieces = {{
      P: '♙', N: '♘', B: '♗', R: '♖', Q: '♕', K: '♔',
      p: '♟', n: '♞', b: '♝', r: '♜', q: '♛', k: '♚'
    }};
    let index = 0;
    let shownMove = null;
    let latestPayloadText = JSON.stringify(data);

    const boardEl = document.getElementById('board');
    const selectEl = document.getElementById('positionSelect');
    const listEl = document.getElementById('positionList');

    function parseFen(fen) {{
      const board = {{}};
      const rows = fen.split(' ')[0].split('/');
      for (let rankIndex = 0; rankIndex < 8; rankIndex++) {{
        let fileIndex = 0;
        const rank = 8 - rankIndex;
        for (const ch of rows[rankIndex]) {{
          if (/\\d/.test(ch)) {{
            fileIndex += Number(ch);
          }} else {{
            board[files[fileIndex] + rank] = ch;
            fileIndex++;
          }}
        }}
      }}
      return board;
    }}

    function applyUci(board, uci) {{
      const next = {{...board}};
      if (!uci || uci.length < 4) return next;
      const from = uci.slice(0, 2);
      const to = uci.slice(2, 4);
      const promotion = uci.length > 4 ? uci[4] : '';
      const piece = next[from];
      delete next[from];
      if (piece) next[to] = promotion ? promote(piece, promotion) : piece;
      return next;
    }}

    function promote(piece, promotion) {{
      const promoted = piece === piece.toUpperCase() ? promotion.toUpperCase() : promotion.toLowerCase();
      return promoted;
    }}

    function renderBoard(position, moveKind=null) {{
      const base = parseFen(position.fen);
      const modelMove = position.move || null;
      const engineMove = position.engine_best_move || null;
      const compare = moveKind === 'both';
      const move = moveKind === 'model' ? modelMove : moveKind === 'engine' ? engineMove : null;
      const display = move && !compare ? applyUci(base, move) : base;
      boardEl.innerHTML = '';
      for (let rank = 8; rank >= 1; rank--) {{
        for (const file of files) {{
          const square = file + rank;
          const cell = document.createElement('div');
          cell.className = `square ${{(files.indexOf(file) + rank) % 2 ? 'light' : 'dark'}}`;
          decorateSquare(cell, square, moveKind, modelMove, engineMove);
          const piece = display[square];
          if (piece) {{
            const pieceEl = document.createElement('div');
            pieceEl.className = 'piece';
            pieceEl.textContent = unicodePieces[piece] || piece;
            cell.appendChild(pieceEl);
          }}
          if (file === 'a' || rank === 1) {{
            const coord = document.createElement('div');
            coord.className = 'coord';
            coord.textContent = file === 'a' && rank === 1 ? square : file === 'a' ? rank : file;
            cell.appendChild(coord);
          }}
          boardEl.appendChild(cell);
        }}
      }}
      renderArrows(moveKind, modelMove, engineMove);
    }}

    function decorateSquare(cell, square, moveKind, modelMove, engineMove) {{
      const modelSquares = moveSquares(modelMove);
      const engineSquares = moveSquares(engineMove);
      if (moveKind === 'model' && modelSquares.includes(square)) cell.classList.add(square === modelSquares[0] ? 'from' : 'to', 'model');
      if (moveKind === 'engine' && engineSquares.includes(square)) cell.classList.add(square === engineSquares[0] ? 'from' : 'to', 'engine');
      if (moveKind !== 'both') return;
      const modelHit = modelSquares.includes(square);
      const engineHit = engineSquares.includes(square);
      if (modelHit && engineHit) {{
        if (modelMove === engineMove) cell.classList.add(square === modelSquares[0] ? 'from' : 'to', 'both');
        cell.classList.add(modelMove === engineMove ? 'both' : 'split-model-engine');
        addTag(cell, modelMove === engineMove ? 'both' : 'model', modelMove === engineMove ? 'Both' : 'LLM');
        if (modelMove !== engineMove) addTag(cell, 'engine', 'AI', true);
      }} else if (modelHit) {{
        cell.classList.add(square === modelSquares[0] ? 'from' : 'to', 'model');
        addTag(cell, 'model', 'LLM');
      }} else if (engineHit) {{
        cell.classList.add(square === engineSquares[0] ? 'from' : 'to', 'engine');
        addTag(cell, 'engine', 'AI');
      }}
    }}

    function addTag(cell, kind, text, lower=false) {{
      const tag = document.createElement('div');
      tag.className = `tag ${{kind}}`;
      tag.textContent = text;
      if (lower) {{
        tag.style.top = '22px';
      }}
      cell.appendChild(tag);
    }}

    function moveSquares(uci) {{
      return uci && uci.length >= 4 ? [uci.slice(0, 2), uci.slice(2, 4)] : [];
    }}

    function renderArrows(moveKind, modelMove, engineMove) {{
      if (!moveKind || moveKind === 'reset') return;
      const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
      svg.setAttribute('viewBox', '0 0 800 800');
      svg.setAttribute('class', 'arrow-layer');
      const defs = document.createElementNS('http://www.w3.org/2000/svg', 'defs');
      defs.appendChild(marker('arrowModel', '#237b64'));
      defs.appendChild(marker('arrowEngine', '#bd7b19'));
      defs.appendChild(marker('arrowBoth', '#2f6fed'));
      svg.appendChild(defs);
      if (moveKind === 'model') addArrow(svg, modelMove, '#237b64', 'arrowModel', 0);
      if (moveKind === 'engine') addArrow(svg, engineMove, '#bd7b19', 'arrowEngine', 0);
      if (moveKind === 'both') {{
        if (modelMove && engineMove && modelMove === engineMove) {{
          addArrow(svg, modelMove, '#2f6fed', 'arrowBoth', 0);
        }} else {{
          addArrow(svg, modelMove, '#237b64', 'arrowModel', -18);
          addArrow(svg, engineMove, '#bd7b19', 'arrowEngine', 18);
        }}
      }}
      boardEl.appendChild(svg);
    }}

    function marker(id, color) {{
      const markerEl = document.createElementNS('http://www.w3.org/2000/svg', 'marker');
      markerEl.setAttribute('id', id);
      markerEl.setAttribute('markerWidth', '10');
      markerEl.setAttribute('markerHeight', '10');
      markerEl.setAttribute('refX', '8');
      markerEl.setAttribute('refY', '3');
      markerEl.setAttribute('orient', 'auto');
      markerEl.setAttribute('markerUnits', 'strokeWidth');
      const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
      path.setAttribute('d', 'M0,0 L0,6 L9,3 z');
      path.setAttribute('fill', color);
      markerEl.appendChild(path);
      return markerEl;
    }}

    function addArrow(svg, move, color, markerId, offset) {{
      if (!move || move.length < 4) return;
      const from = squareCenter(move.slice(0, 2));
      const to = squareCenter(move.slice(2, 4));
      const dx = to.x - from.x;
      const dy = to.y - from.y;
      const len = Math.hypot(dx, dy) || 1;
      const nx = -dy / len * offset;
      const ny = dx / len * offset;
      const line = document.createElementNS('http://www.w3.org/2000/svg', 'line');
      line.setAttribute('x1', from.x + nx);
      line.setAttribute('y1', from.y + ny);
      line.setAttribute('x2', to.x + nx);
      line.setAttribute('y2', to.y + ny);
      line.setAttribute('stroke', color);
      line.setAttribute('stroke-width', '18');
      line.setAttribute('stroke-linecap', 'round');
      line.setAttribute('opacity', '0.86');
      line.setAttribute('marker-end', `url(#${{markerId}})`);
      svg.appendChild(line);
    }}

    function squareCenter(square) {{
      const file = files.indexOf(square[0]);
      const rank = Number(square[1]);
      return {{ x: file * 100 + 50, y: (8 - rank) * 100 + 50 }};
    }}

    function setPosition(nextIndex) {{
      const rows = combinedRows();
      index = Math.max(0, Math.min(rows.length - 1, nextIndex));
      shownMove = null;
      const position = rows[index];
      selectEl.value = String(index);
      document.querySelectorAll('.list button').forEach((button, i) => button.classList.toggle('active', i === index));
      document.getElementById('positionTitle').textContent = `${{index + 1}}. ${{position.position_name}}`;
      document.getElementById('positionSubtitle').textContent = `${{position.position_id}} · ${{position.category}} · ${{position.side_to_move}} to move`;
      document.getElementById('scoreMetric').textContent = position._pending ? '...' : Number(position.score || 0).toFixed(3);
      document.getElementById('lossMetric').textContent = position._pending ? 'waiting' : position.centipawn_loss === null || position.centipawn_loss === undefined ? 'forfeit' : position.centipawn_loss;
      document.getElementById('matchMetric').textContent = position._pending ? 'waiting' : position.exact_engine_match ? 'yes' : 'no';
      document.getElementById('modelMove').textContent = position._pending ? 'waiting' : position.move ? `${{position.move}} ${{position.move_san || ''}}` : position.outcome;
      document.getElementById('engineMove').textContent = position._pending ? 'waiting' : position.engine_best_move ? `${{position.engine_best_move}} ${{position.engine_best_san || ''}}` : 'none';
      document.getElementById('modelNote').textContent = position._pending ? 'The LLM has not answered this position yet.' : moveExplanation(position);
      document.getElementById('engineNote').textContent = position._pending ? 'Stockfish analysis will appear when this row completes.' : engineExplanation(position);
      document.getElementById('waitingPanel').hidden = !position._pending;
      document.getElementById('responseText').textContent = position.response || position.error || '';
      renderBoard(position);
      updateButtons(position);
    }}

    function showMove(kind) {{
      shownMove = kind;
      const position = combinedRows()[index];
      if (position._pending) return;
      renderBoard(position, kind);
    }}

    function buildSelectors() {{
      selectEl.innerHTML = '';
      listEl.innerHTML = '';
      combinedRows().forEach((position, i) => {{
        const option = document.createElement('option');
        option.value = String(i);
        option.textContent = `${{i + 1}}. ${{position.position_id}}`;
        selectEl.appendChild(option);

        const button = document.createElement('button');
        const name = document.createElement('span');
        name.textContent = `${{i + 1}}. ${{position.position_name}}`;
        const pill = document.createElement('span');
        pill.className = `pill ${{position._pending ? 'waiting' : position.outcome === 'legal_move' ? 'ok' : ''}}`;
        pill.textContent = position._pending ? 'waiting' : position.outcome === 'legal_move' ? Number(position.score || 0).toFixed(2) : 'forfeit';
        button.appendChild(name);
        button.appendChild(pill);
        button.addEventListener('click', () => setPosition(i));
        listEl.appendChild(button);
      }});
    }}

    function combinedRows() {{
      const results = new Map((data.positions || []).map(item => [item.position_id, item]));
      const manifest = data.position_manifest && data.position_manifest.length ? data.position_manifest : data.positions || [];
      return manifest.map((meta, i) => {{
        const result = results.get(meta.position_id);
        if (result) return {{...meta, ...result, _pending: false}};
        return {{...meta, side_to_move: meta.side_to_move || fenSide(meta.fen), _pending: true}};
      }});
    }}

    function fenSide(fen) {{
      return fen && fen.split(' ')[1] === 'b' ? 'black' : 'white';
    }}

    function moveExplanation(position) {{
      if (position.outcome !== 'legal_move') return 'No legal move was accepted, so this row scores zero.';
      if (position.exact_engine_match) return 'The LLM matched the master AI top move exactly.';
      return `The LLM chose a legal move, losing ${{position.centipawn_loss}} centipawns versus the master AI top line.`;
    }}

    function engineExplanation(position) {{
      if (!position.engine_best_move) return 'No engine move was available.';
      const line = position.engine_lines && position.engine_lines[0];
      return line ? `Top line score: ${{line.score_cp}} cp. Principal variation starts ${{line.pv.slice(0, 5).join(' ')}}.` : 'Top move from the master AI.';
    }}

    function updateButtons(position) {{
      document.getElementById('modelBtn').disabled = position._pending || !position.move;
      document.getElementById('engineBtn').disabled = position._pending || !position.engine_best_move;
      document.getElementById('bothBtn').disabled = position._pending || (!position.move && !position.engine_best_move);
    }}

    function updateHeader() {{
      const completed = data.completed_positions ?? (data.positions || []).length;
      const total = data.total_positions || combinedRows().length;
      const score = Number((data.summary || {{}}).normalized_score || 0).toFixed(2);
      const legal = (data.summary || {{}}).legal_moves || 0;
      const status = data.status === 'running' ? 'Running' : 'Complete';
      document.getElementById('runMeta').textContent = `${{status}} · ${{data.model_name}} · ${{completed}}/${{total}} positions · score ${{score}} · ${{legal}} legal`;
      document.getElementById('statusDot').classList.toggle('running', data.status === 'running');
    }}

    async function refreshLiveData() {{
      if (!liveSource) return;
      try {{
        const response = await fetch(`${{liveSource}}?t=${{Date.now()}}`, {{cache: 'no-store'}});
        if (!response.ok) return;
        const text = await response.text();
        if (text === latestPayloadText) return;
        const currentId = combinedRows()[index]?.position_id;
        latestPayloadText = text;
        data = JSON.parse(text);
        buildSelectors();
        const nextIndex = Math.max(0, combinedRows().findIndex(row => row.position_id === currentId));
        setPosition(nextIndex);
        updateHeader();
      }} catch (error) {{
        // The benchmark may be between writes. Keep showing the last good state.
      }}
    }}

    function init() {{
      const engine = data.engine || {{}};
      document.getElementById('engineMeta').textContent = `Master AI · ${{engine.threads || '?'}} threads · ${{engine.hash_mb || '?'}} MB hash · ${{engine.movetime_ms || '?'}} ms`;
      buildSelectors();
      updateHeader();
      setPosition(0);
      document.getElementById('prevBtn').addEventListener('click', () => setPosition(index - 1));
      document.getElementById('nextBtn').addEventListener('click', () => setPosition(index + 1));
      document.getElementById('modelBtn').addEventListener('click', () => showMove('model'));
      document.getElementById('engineBtn').addEventListener('click', () => showMove('engine'));
      document.getElementById('bothBtn').addEventListener('click', () => showMove('both'));
      document.getElementById('resetBtn').addEventListener('click', () => setPosition(index));
      selectEl.addEventListener('change', event => setPosition(Number(event.target.value)));
      window.addEventListener('keydown', event => {{
        if (event.key === 'ArrowLeft') setPosition(index - 1);
        if (event.key === 'ArrowRight') setPosition(index + 1);
        if (event.key.toLowerCase() === 'm') showMove('model');
        if (event.key.toLowerCase() === 's') showMove('engine');
        if (event.key.toLowerCase() === 'b') showMove('both');
      }});
      if (liveSource) setInterval(refreshLiveData, 1500);
    }}

    init();
  </script>
</body>
</html>
"""
