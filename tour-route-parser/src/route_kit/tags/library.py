"""The data the tag stage reads: alias library, vocabulary, lookups, main and auxiliary rules.

Each file carries a human-bumped ``version`` and the loader adds a content hash, so the
version string recorded on a tag ("1@3f2a9c1e") changes on any edit, bumped or not.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

import yaml

DATA = Path(__file__).resolve().parent / "data"


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFKC", text or "")
    return re.sub(r"[\s【】\[\]「」『』“”\"'‘’·•・,，。.、:：;；()（）<>《》!！?？\-—–~_|/]", "", text).lower()


def _load(path: Path) -> tuple[dict, str]:
    raw = path.read_bytes()
    data = yaml.safe_load(raw) or {}
    digest = hashlib.sha256(raw).hexdigest()[:8]
    return data, f"{data.get('version', 0)}@{digest}"


@dataclass
class Place:
    canonical: str
    kind: str
    country: str = ""
    continent: str = ""
    region: str = ""
    line: str = ""


class Aliases:
    def __init__(self, path: Path = DATA / "aliases.yaml"):
        data, self.version = _load(path)
        self.entries: dict[str, Place] = {}
        self._index: dict[tuple[str, str], str] = {}
        for entry in data.get("entries", []):
            place = Place(
                canonical=entry["canonical"],
                kind=entry["kind"],
                country=entry.get("country", ""),
                continent=entry.get("continent", ""),
                region=entry.get("region", ""),
                line=entry.get("line", ""),
            )
            self.entries[(place.kind, place.canonical)] = place
            for name in [place.canonical, *entry.get("aliases", [])]:
                self._index[(place.kind, _norm(name))] = place.canonical

    def canonical(self, name: str, kind: str) -> str | None:
        """The canonical name for ``name`` of this kind, or None when the library has no entry."""
        key = _norm(name)
        if not key:
            return None
        hit = self._index.get((kind, key))
        if hit:
            return hit
        # "伦敦市", "巴黎（含门票）"-style suffixes: try the longest alias the text starts with.
        for (k, alias), canonical in self._index.items():
            if k == kind and len(alias) >= 2 and key.startswith(alias) and len(key) - len(alias) <= 2:
                return canonical
        return None

    def place(self, canonical: str, kind: str) -> Place | None:
        return self.entries.get((kind, canonical))

    def country_of_city(self, city: str) -> str:
        place = self.place(city, "city")
        return place.country if place else ""

    def continent_of(self, country: str) -> str:
        place = self.place(country, "country")
        return place.continent if place else ""

    def region_of(self, country: str) -> str:
        place = self.place(country, "country")
        return place.region if place else ""


@dataclass
class Word:
    word: str
    dimension: str
    scope: str = "通用"
    group: str = ""
    definition: str = ""


class Vocabulary:
    def __init__(self, path: Path = DATA / "vocabulary.yaml"):
        data, self.version = _load(path)
        self.words: dict[tuple[str, str], Word] = {}
        self.cardinality: dict[str, str] = {}
        for dimension, spec in (data.get("dimensions") or {}).items():
            self.cardinality[dimension] = spec.get("cardinality", "multi")
            for entry in spec.get("words", []):
                word = Word(
                    word=entry["word"],
                    dimension=dimension,
                    scope=entry.get("scope", "通用"),
                    group=entry.get("group", ""),
                    definition=entry.get("definition", ""),
                )
                self.words[(dimension, word.word)] = word
        self.merged_into: dict[str, str] = {
            d["word"]: d.get("merged_into", "") for d in data.get("deprecated", []) or []
        }

    def active(self, dimension: str, scopes: set[str]) -> list[Word]:
        return [
            w
            for (d, _), w in self.words.items()
            if d == dimension and w.scope in scopes and w.word not in self.merged_into
        ]

    def resolve(self, dimension: str, word: str) -> str:
        """A deprecated word resolves to the word it was merged into."""
        return self.merged_into.get(word) or word

    def dimensions(self) -> list[str]:
        return list(self.cardinality)


class Lookups:
    def __init__(self, path: Path = DATA / "lookups.yaml"):
        self.data, self.version = _load(path)

    @property
    def holidays(self) -> dict:
        return self.data.get("holidays", {})

    @property
    def seasons(self) -> dict:
        return self.data.get("seasons", {})

    @property
    def cruise_regions(self) -> dict:
        return self.data.get("cruise_regions", {})


class Rules:
    """``main.yaml`` (thresholds) + ``promoted.yaml`` (declarative rules a person promoted)
    form the main track; ``aux.yaml`` is the auxiliary track."""

    def __init__(
        self,
        main: Path = DATA / "rules" / "main.yaml",
        aux: Path = DATA / "rules" / "aux.yaml",
        promoted: Path = DATA / "rules" / "promoted.yaml",
    ):
        self.main_path, self.aux_path, self.promoted_path = main, aux, promoted
        self.main, main_version = _load(main)
        self.aux, self.aux_version = _load(aux)
        if promoted.exists():
            self.promoted, promoted_version = _load(promoted)
            self.main_version = f"{main_version}+{promoted_version}"
        else:
            self.promoted, self.main_version = {"rules": []}, main_version

    @property
    def promoted_rules(self) -> list[dict]:
        return list(self.promoted.get("rules") or [])

    def get(self, *keys, default=None):
        node = self.main
        for key in keys:
            if not isinstance(node, dict) or key not in node:
                return default
            node = node[key]
        return node

    @property
    def aux_rules(self) -> list[dict]:
        return list(self.aux.get("rules") or [])


@dataclass
class Library:
    aliases: Aliases = field(default_factory=Aliases)
    vocabulary: Vocabulary = field(default_factory=Vocabulary)
    lookups: Lookups = field(default_factory=Lookups)
    rules: Rules = field(default_factory=Rules)

    def versions(self) -> dict[str, str]:
        return {
            "main_rules": self.rules.main_version,
            "aux_rules": self.rules.aux_version,
            "vocab": self.vocabulary.version,
            "aliases": self.aliases.version,
            "lookups": self.lookups.version,
        }
