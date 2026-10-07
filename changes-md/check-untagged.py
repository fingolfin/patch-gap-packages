import importlib.util, re, datetime as dt
from pathlib import Path
spec = importlib.util.spec_from_file_location("b", "patchit-changes-b.py"); b = importlib.util.module_from_spec(spec); spec.loader.exec_module(b)
for name in Path("groupD.txt").read_text().split():
    d = Path(f"drafts/{name}.md")
    if not d.exists():
        continue
    h = b.History(Path(name))
    if not h.tags:
        continue
    first = min(t[2] for t in h.tags.values())
    odd = []
    for m in re.finditer(r"(?m)^## (\S+) \((\d{4}-\d\d-\d\d)\)$", d.read_text()):
        ver, date = m[1], dt.date.fromisoformat(m[2])
        if b.norm_ver(ver) not in h.tags and date >= first:
            odd.append(f"{ver} ({date})")
    if odd:
        print(f"{name} (first tag {first}): " + ", ".join(odd))
