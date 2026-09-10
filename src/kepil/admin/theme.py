"""Оформление панели.

Панель оператора — плотный рабочий инструмент, а не витрина: тёмный фон, чтобы
не выжигать глаза в смену, моноширинный шрифт для всего, что сверяют глазами
(хеши, действия, идентификаторы), и цвет только там, где он означает решение:
разрешено, отказано, ждёт человека.
"""

CSS = """
:root{
  --bg:#12140F; --panel:#191C16; --panel-2:#20241D; --line:#2E332A;
  --ink:#E9ECE3; --ink-2:#A6AE9E; --ink-3:#767E70;
  --ok:#7FBFA6; --deny:#D98A7B; --wait:#D6AC5A; --accent:#7FBFA6;
}
*{box-sizing:border-box}
html,body{height:100%}
body{margin:0;background:var(--bg);color:var(--ink);display:flex;
  font:14px/1.5 "Segoe UI",system-ui,sans-serif}
a{color:var(--accent);text-decoration:none}
a:hover{text-decoration:underline}
.mono,code{font-family:Consolas,"Cascadia Mono",monospace}

nav{width:210px;flex:none;background:var(--panel);border-right:1px solid var(--line);
  padding:16px 0;display:flex;flex-direction:column;height:100vh;position:sticky;top:0}
nav .brand{padding:0 18px 16px;border-bottom:1px solid var(--line);margin-bottom:10px}
nav .brand b{font-size:18px;letter-spacing:.02em}
nav .brand span{display:block;color:var(--ink-3);font-size:11.5px;margin-top:2px}
nav a{display:flex;justify-content:space-between;gap:8px;padding:8px 18px;
  color:var(--ink-2);font-size:13.5px;border-left:2px solid transparent}
nav a:hover{color:var(--ink);text-decoration:none;background:var(--panel-2)}
nav a.on{color:var(--ink);border-left-color:var(--accent);background:var(--panel-2)}
nav a .count{color:var(--ink-3);font-family:Consolas,monospace;font-size:11.5px}
nav .foot{margin-top:auto;padding:12px 18px 0;border-top:1px solid var(--line);
  color:var(--ink-3);font-size:11.5px}

main{flex:1;min-width:0;padding:22px 30px 60px;max-width:1180px}
h1{font-size:21px;margin:0 0 4px;font-weight:600;letter-spacing:.01em}
.lede{color:var(--ink-3);font-size:13px;margin:0 0 22px}
h2{font-size:11px;letter-spacing:.11em;text-transform:uppercase;color:var(--ink-3);
  margin:26px 0 11px;font-weight:600}
h2:first-of-type{margin-top:0}

.grid{display:grid;gap:14px}
.g2{grid-template-columns:repeat(auto-fit,minmax(300px,1fr))}
.g3{grid-template-columns:repeat(auto-fit,minmax(220px,1fr))}
.card{background:var(--panel);border:1px solid var(--line);padding:14px 16px}
.card h3{margin:0 0 8px;font-size:14.5px;font-weight:600}
.card p{margin:0 0 8px;color:var(--ink-2);font-size:13px}
.card p:last-child{margin-bottom:0}
.tile .n{font-family:Consolas,monospace;font-size:26px;line-height:1.1}
.tile .l{color:var(--ink-3);font-size:12px;margin-top:4px}

table{width:100%;border-collapse:collapse;font-size:13px}
th{text-align:left;font-weight:500;color:var(--ink-3);font-size:11px;
  letter-spacing:.08em;text-transform:uppercase;padding:0 12px 8px 0;
  border-bottom:1px solid var(--line)}
td{padding:8px 12px 8px 0;border-bottom:1px solid var(--line);vertical-align:top}
tr:last-child td{border-bottom:none}
td.mono,th.mono{font-family:Consolas,monospace;font-size:12px}

.pill{display:inline-block;font-size:11.5px;padding:2px 8px;border:1px solid var(--line);
  border-radius:2px;color:var(--ink-2);white-space:nowrap}
.pill.ok{color:var(--ok);border-color:#2C4A40}
.pill.deny{color:var(--deny);border-color:#4A2E28}
.pill.wait{color:var(--wait);border-color:#4A3D1E}

.steps{display:flex;flex-direction:column;gap:1px;background:var(--line);
  border:1px solid var(--line)}
.step{display:grid;grid-template-columns:22px 1fr auto;gap:10px;
  background:var(--panel);padding:9px 13px}
.step.idle{background:var(--panel-2);opacity:.45}
.step .m{font-family:Consolas,monospace}
.step.ok .m{color:var(--ok)} .step.deny .m{color:var(--deny)} .step.wait .m{color:var(--wait)}
.step .t{font-size:13.5px}
.step .a{font-family:Consolas,monospace;font-size:11.5px;color:var(--ink-3);margin-top:2px}
.step .w{font-size:12.5px;margin-top:5px;padding-left:10px;border-left:2px solid var(--line)}
.step.deny .w{color:var(--deny)} .step.wait .w{color:var(--wait)} .step.ok .w{color:var(--ink-3)}
.step .c{font-family:Consolas,monospace;font-size:11.5px;color:var(--ink-3);white-space:nowrap}

form.inline{display:inline}
label{display:block;color:var(--ink-3);font-size:11.5px;letter-spacing:.06em;
  text-transform:uppercase;margin:14px 0 5px}
label .hint{text-transform:none;letter-spacing:0;color:var(--ink-3);font-size:12px;
  display:block;margin-top:3px;opacity:.85}
input[type=text],input[type=number],select,textarea{width:100%;background:var(--panel-2);
  border:1px solid var(--line);color:var(--ink);padding:8px 10px;font:inherit;font-size:13.5px}
textarea{font-family:Consolas,monospace;font-size:12.5px;line-height:1.6;resize:vertical}
input:focus,select:focus,textarea:focus{outline:none;border-color:var(--accent)}
.row{display:flex;gap:10px;flex-wrap:wrap;align-items:center;margin-top:16px}
.cols{display:grid;gap:14px;grid-template-columns:repeat(auto-fit,minmax(240px,1fr))}

button{font:inherit;font-size:13.5px;padding:8px 15px;border:1px solid var(--line);
  background:var(--panel-2);color:var(--ink);cursor:pointer}
button:hover{border-color:var(--accent)}
button:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
button.primary{background:var(--accent);color:#10130F;border-color:var(--accent);font-weight:600}
button.danger{color:var(--deny)}
button:disabled{opacity:.35;cursor:not-allowed}

.msg{padding:11px 14px;border:1px solid var(--line);margin-bottom:18px;font-size:13.5px}
.msg.ok{border-left:3px solid var(--ok)}
.msg.err{border-left:3px solid var(--deny);color:var(--deny)}
.meter{height:4px;background:var(--panel-2);border:1px solid var(--line);margin-top:6px}
.meter i{display:block;height:100%;background:var(--accent)}
dl.kv{display:grid;grid-template-columns:170px 1fr;gap:6px 14px;margin:0;font-size:13px}
dl.kv dt{color:var(--ink-3)}
dl.kv dd{margin:0;overflow-wrap:anywhere}
.empty{color:var(--ink-3);font-size:13px;padding:10px 0}
"""
