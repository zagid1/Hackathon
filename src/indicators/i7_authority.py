"""И7 Полномочия (уровень контракта): должность подписанта не имеет права SIGN_CONTRACT
по регламенту (position_authorities)."""

from __future__ import annotations

from .base import Context, Signal, date_ru, lower_first, short_name

CODE = "I7"
ACTION = "SIGN_CONTRACT"


def _allowed_titles(ctx: Context) -> str:
    titles = sorted({ctx.positions[pid] for pid, acts in ctx.authorities.items() if ACTION in acts})
    generic = []
    for t in titles:
        t = "директоры департаментов" if t.startswith("Директор Департамента") else lower_first(t)
        if t not in generic:
            generic.append(t)
    return ", ".join(generic)


def compute(ctx: Context) -> list[Signal]:
    allowed = _allowed_titles(ctx)
    out = []
    for cid, c in sorted(ctx.contracts.items()):
        e = c["signer"]
        if ctx.can(e, ACTION):
            continue
        emp = ctx.employees[e]
        out.append(Signal(
            CODE, "contract", cid, e, None, None, "регламент полномочий",
            f"Контракт от {date_ru(c['signed_at'])} подписал {lower_first(emp['title'])} "
            f"{short_name(emp['full_name'])}; право подписи контрактов по регламенту есть только у: {allowed}.",
            ctx.protocol_fragments(c["procurement_id"], c["supplier"], last=True)))
    return out
