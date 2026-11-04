"""И2 Аффилированность (уровень контракта).

Сигнал, если в графе есть путь длины <= i2_max_path от участника закупки (ответственный, подписант,
член комиссии) до поставщика или его директора/учредителя по рёбрам RELATIVE, EX_EMPLOYER, SAME_PROJECT.
"""

from __future__ import annotations

from src.graph.build import affiliation_graph, node, parse_node, shortest_path_to

from .base import Context, Signal, lower_first, short_name

CODE = "I2"

COMMISSION_ROLES = {"CHAIR": "председатель комиссии", "DEPUTY_CHAIR": "заместитель председателя комиссии",
                    "MEMBER": "член комиссии", "SECRETARY": "секретарь комиссии"}
REL_TEXT = {"RELATIVE": "родственник", "EX_EMPLOYER": "бывший работодатель", "SAME_PROJECT": "общая проектная группа"}


def compute(ctx: Context) -> list[Signal]:
    max_len = ctx.icfg["i2_max_path"]
    gaff = affiliation_graph(ctx.graph)
    out = []
    for cid, c in sorted(ctx.contracts.items()):
        p = ctx.procurements[c["procurement_id"]]
        roles: dict[int, list[str]] = {}
        roles.setdefault(p["responsible"], []).append("ответственный за закупку")
        for mid, role in ctx.commission_employees(p["commission"]):
            roles.setdefault(mid, []).append(COMMISSION_ROLES[role])
        roles.setdefault(c["signer"], []).append("подписант контракта")

        sup = c["supplier"]
        targets = {node("organization", sup)} | {node("person", pid) for pid, _ in ctx.org_people[sup]}
        path = shortest_path_to(gaff, [node("employee", e) for e in roles], targets, max_len)
        if path is None:
            continue

        emp = parse_node(path[0])[1]
        hops = []
        evidence: list[int] = []
        for a, b in zip(path, path[1:]):
            data = gaff.edges[a, b]
            hops.append(REL_TEXT[data["rel"]])
            if data.get("evidence_doc_id"):
                gid = next(g for g, info in ctx.groups.items() if info["doc_id"] == data["evidence_doc_id"])
                evidence += ctx.member_fragments(gid, [parse_node(a), parse_node(b)])
        names = [_describe(ctx, n, sup) for n in path]
        chain = names[0]
        for hop, name in zip(hops, names[1:]):
            chain += f" —[{hop}]— {name}"

        role_text = ", ".join(roles[emp])
        basis = ""
        if any(r in COMMISSION_ROLES.values() for r in roles[emp]):
            gid = p["commission"]
            evidence = ctx.member_fragments(gid, [("employee", emp)]) + evidence
            basis = f" Участие в комиссии: {ctx.doc_ref(ctx.groups[gid]['doc_id'])}."
        evidence += ctx.protocol_fragments(p["id"], sup, last=True)
        out.append(Signal(
            CODE, "contract", cid, emp, float(len(path) - 1), float(max_len), "абсолютное правило",
            f"Поставщик {ctx.orgs[sup]} связан с участником закупки ({role_text}): {chain}.{basis}",
            list(dict.fromkeys(evidence))))
    return out


def _describe(ctx: Context, n: str, supplier: int) -> str:
    kind, i = parse_node(n)
    if kind == "employee":
        return f"{short_name(ctx.employees[i]['full_name'])} ({lower_first(ctx.employees[i]['title'])})"
    if kind == "organization":
        return ctx.orgs[i] + (" (поставщик)" if i == supplier else "")
    roles = [r for pid, r in ctx.org_people[supplier] if pid == i]
    if roles:
        what = " и ".join({"DIRECTOR": "директор", "FOUNDER": "учредитель"}[r] for r in sorted(roles))
        return f"{short_name(ctx.persons[i])} ({what} поставщика)"
    return short_name(ctx.persons[i])
