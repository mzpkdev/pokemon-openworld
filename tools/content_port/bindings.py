"""Read-only lookup over the checked persistent identity ledger."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Iterable, Mapping

from .errors import ContentPortError


_RESOLVABLE_STATES = frozenset(
    {
        "allocated-binding",
        "published-binding",
        "trainer-defeat-bitmap",
        "trainer-defeat-flag",
    }
)
_LEDGER_STATES = _RESOLVABLE_STATES | {"published-tombstone"}


@dataclass(frozen=True)
class PersistentBinding:
    domain: str
    symbol: str
    value: int
    storage: str
    state: str
    alias_of: str | None = None


class BindingIndex:
    def __init__(self, bindings: Iterable[PersistentBinding]) -> None:
        all_by_symbol: dict[tuple[str, str], PersistentBinding] = {}
        by_symbol: dict[tuple[str, str], PersistentBinding] = {}
        domains_by_symbol: dict[str, set[str]] = {}
        by_slot: dict[tuple[str, str, int], PersistentBinding] = {}
        pending = list(bindings)
        for binding in pending:
            identity = (binding.domain, binding.symbol)
            if identity in all_by_symbol:
                raise ContentPortError(
                    f"persistent ledger duplicates symbol {binding.domain}:{binding.symbol}"
                )
            if binding.state not in _LEDGER_STATES:
                raise ContentPortError(
                    f"{binding.symbol}: unallocated persistent state {binding.state}"
                )
            all_by_symbol[identity] = binding
            if binding.state not in _RESOLVABLE_STATES:
                continue
            by_symbol[identity] = binding
            domains_by_symbol.setdefault(binding.symbol, set()).add(binding.domain)
        for binding in pending:
            slot = (binding.domain, binding.storage, binding.value)
            owner = by_slot.get(slot)
            if owner is None:
                by_slot[slot] = binding
                continue
            aliases = {binding.alias_of, owner.alias_of}
            if owner.symbol not in aliases and binding.symbol not in aliases:
                raise ContentPortError(
                    f"persistent ledger collision {binding.domain}/{binding.storage}/{binding.value}: "
                    f"{owner.symbol} and {binding.symbol}"
                )
        for binding in pending:
            if binding.alias_of is None:
                continue
            target = all_by_symbol.get((binding.domain, binding.alias_of))
            if target is None:
                raise ContentPortError(
                    f"{binding.symbol}: alias target {binding.alias_of} is missing"
                )
            if (binding.domain, binding.storage, binding.value) != (
                target.domain,
                target.storage,
                target.value,
            ):
                raise ContentPortError(
                    f"{binding.symbol}: alias disagrees with {binding.alias_of}"
                )
        self._by_symbol = MappingProxyType(by_symbol)
        self._domains_by_symbol = MappingProxyType(
            {
                symbol: frozenset(domains)
                for symbol, domains in domains_by_symbol.items()
            }
        )

    def resolve(self, symbol: str, *, domain: str | None = None) -> PersistentBinding:
        if domain is None:
            domains = self._domains_by_symbol.get(symbol, frozenset())
            if len(domains) > 1:
                rendered = ", ".join(sorted(domains))
                raise ContentPortError(
                    f"persistent symbol {symbol} is ambiguous across domains: {rendered}"
                )
            domain = next(iter(domains), None)
        binding = self._by_symbol.get((domain, symbol)) if domain is not None else None
        if binding is None:
            raise ContentPortError(f"persistent symbol {symbol} has no ledger binding")
        if binding.alias_of:
            target = self._by_symbol.get((binding.domain, binding.alias_of))
            if target is not None:
                return target
        return binding

    def __contains__(self, symbol: object) -> bool:
        return isinstance(symbol, str) and symbol in self._domains_by_symbol


def load_binding_index(path: Path | str) -> BindingIndex:
    source = Path(path)
    try:
        document = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContentPortError(f"{source}: invalid persistent ledger: {exc}") from exc
    if not isinstance(document, Mapping) or not isinstance(
        document.get("entries"), list
    ):
        raise ContentPortError(f"{source}: persistent ledger requires an entries array")
    bindings: list[PersistentBinding] = []
    for index, entry in enumerate(document["entries"]):
        pointer = f"{source}/entries/{index}"
        if not isinstance(entry, Mapping):
            raise ContentPortError(f"{pointer}: binding must be an object")
        try:
            alias = entry.get("alias")
            alias_of = alias.get("of") if isinstance(alias, Mapping) else alias
            state = entry["state"]
            state_kind = state["kind"] if isinstance(state, Mapping) else state
            binding = PersistentBinding(
                domain=str(entry["domain"]),
                symbol=str(entry["symbol"]),
                value=int(entry["value"]),
                storage=str(entry["storage"]),
                state=str(state_kind),
                alias_of=str(alias_of) if alias_of is not None else None,
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ContentPortError(f"{pointer}: malformed binding: {exc}") from exc
        bindings.append(binding)
    return BindingIndex(bindings)


def resolve_bindings(
    symbols: Iterable[str], index: BindingIndex
) -> Mapping[str, PersistentBinding]:
    return MappingProxyType(
        {symbol: index.resolve(symbol) for symbol in sorted(set(symbols))}
    )
