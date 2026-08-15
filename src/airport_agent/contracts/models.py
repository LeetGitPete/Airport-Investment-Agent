"""Core domain types. Pure data — no logic beyond validation and tiny helpers."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Horizon = Literal["12m", "3y", "5y", "10y"]
HubSize = Literal["large", "medium", "small", "nonhub"]
Tier = Literal["A", "B", "C"]
Direction = Literal["up", "down"]  # "up": higher value ⇒ more expansion-attractive
Pillar = Literal["P1", "P2", "P3", "P4", "P5"]
PeerGroup = Literal["hub_class", "region", "all"]
MetricHorizon = Literal["12m", "3y", "5y", "10y", "static", "forecast"]

HORIZONS: tuple[Horizon, ...] = ("12m", "3y", "5y", "10y")


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class AirportRef(_Frozen):
    iata: str
    icao: str | None = None
    faa_locid: str
    name: str
    city: str
    state: str
    faa_region: str  # FAA region code, e.g. ANE (New England)
    hub_size: HubSize
    lat: float
    lon: float

    @field_validator("iata", "faa_locid", "state", "faa_region", mode="before")
    @classmethod
    def _upper(cls, v: str) -> str:
        return v.strip().upper() if isinstance(v, str) else v

    @field_validator("icao", mode="before")
    @classmethod
    def _upper_opt(cls, v: str | None) -> str | None:
        return v.strip().upper() if isinstance(v, str) else v


class SourceVintage(_Frozen):
    source_id: str
    description: str
    period_start: str | None  # "YYYY-MM" or "YYYY"
    period_end: str | None
    fetched_at: str  # ISO timestamp
    url: str | None = None


class QualityFlag(_Frozen):
    code: str
    message: str


class Metric(_Frozen):
    id: str
    value: float | None
    unit: str
    horizon: MetricHorizon
    period_start: str | None
    period_end: str | None
    source_id: str
    vintage: str
    quality: list[QualityFlag] = Field(default_factory=list)


class MetricSpec(_Frozen):
    id: str
    name: str
    definition: str
    formula: str
    unit: str
    direction: Direction
    pillar: Pillar
    tier: Tier
    sources: list[str]
    horizons: list[MetricHorizon]
    caveats: list[str] = Field(default_factory=list)


class AirportFilter(BaseModel):
    model_config = ConfigDict(extra="forbid")
    states: list[str] = Field(default_factory=list)
    faa_regions: list[str] = Field(default_factory=list)
    cbsa_codes: list[str] = Field(default_factory=list)
    iatas: list[str] = Field(default_factory=list)
    hub_sizes: list[HubSize] = Field(default_factory=list)
    name_contains: str | None = None
    limit: int = Field(default=50, ge=1, le=600)

    @field_validator("states", "faa_regions", "cbsa_codes", "iatas", mode="before")
    @classmethod
    def _upper_list(cls, v: list[str]) -> list[str]:
        if not isinstance(v, list):
            return v
        return [s.strip().upper() if isinstance(s, str) else s for s in v]


class FeatureMatrix(BaseModel):
    """Dense numeric matrix for the Deterministic Analyst. values[i][j] = airport i, metric j (None = missing)."""
    model_config = ConfigDict(extra="forbid")
    airports: list[AirportRef]
    metric_ids: list[str]
    horizon: Horizon
    values: list[list[float | None]]
    peer_group: PeerGroup
    vintages: list[SourceVintage] = Field(default_factory=list)

    @model_validator(mode="after")
    def _shape(self) -> FeatureMatrix:
        if len(self.values) != len(self.airports):
            raise ValueError("values must have one row per airport")
        for row in self.values:
            if len(row) != len(self.metric_ids):
                raise ValueError("each row must have one value per metric_id")
        return self

    def coverage(self) -> float:
        total = len(self.airports) * len(self.metric_ids)
        if total == 0:
            return 0.0
        present = sum(1 for row in self.values for v in row if v is not None)
        return present / total

    def column(self, metric_id: str) -> list[float | None]:
        j = self.metric_ids.index(metric_id)
        return [row[j] for row in self.values]


class RouteRow(_Frozen):
    dest: str
    dest_name: str | None
    distance_mi: float
    departures: int
    seats: int
    passengers: int
    freight_lb: float
    is_international: bool


class RouteTable(_Frozen):
    iata: str
    period_start: str
    period_end: str
    source_id: str
    vintage: str
    rows: list[RouteRow]
    truncated: bool


class CuratedFact(_Frozen):
    iata: str
    category: str  # slot_level | hourly_cap | declared_capacity | gates | constraint | project | other
    text: str
    value: float | str | None = None
    source_url: str
    as_of: str
    expires: str | None = None


class LiveStatus(_Frozen):
    iata: str
    delay_programs: list[str]
    ground_stop: bool
    closure: bool
    latest_month: dict[str, float] | None
    fetched_at: str
    source_ids: list[str]


class AirportProfile(BaseModel):
    """Structured JSON view for the LLM specialists (≤ ~2k tokens)."""
    model_config = ConfigDict(extra="forbid")
    ref: AirportRef
    metrics: dict[str, list[Metric]]  # keyed by horizon ("12m", "5y", "static", "forecast")
    forecast: dict[str, float | str | None]
    routes_summary: dict[str, float | str | None]
    curated_facts: list[CuratedFact]
    live: LiveStatus | None
    data_quality_notes: list[str]
    vintages: list[SourceVintage]
