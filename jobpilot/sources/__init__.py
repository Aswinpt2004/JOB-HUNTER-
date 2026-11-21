from jobpilot.sources.base import (
    BaseSource,
    register_source,
    get_registered_sources,
    get_source,
    run_all_enabled_sources
)

# Import plugins to auto-register
from jobpilot.sources.adzuna import AdzunaSource
from jobpilot.sources.jooble import JoobleSource
from jobpilot.sources.careerjet import CareerjetSource
from jobpilot.sources.jsearch import JSearchSource
from jobpilot.sources.remotive import RemotiveSource
from jobpilot.sources.arbeitnow import ArbeitnowSource
from jobpilot.sources.ats import ATSSource
from jobpilot.sources.kerala_parks import KeralaParksSource
from jobpilot.sources.company_careers import CompanyCareersSource
from jobpilot.sources.manual import ManualImportSource

__all__ = [
    "BaseSource",
    "register_source",
    "get_registered_sources",
    "get_source",
    "run_all_enabled_sources",
    "AdzunaSource",
    "JoobleSource",
    "CareerjetSource",
    "JSearchSource",
    "RemotiveSource",
    "ArbeitnowSource",
    "ATSSource",
    "KeralaParksSource",
    "CompanyCareersSource",
    "ManualImportSource"
]

