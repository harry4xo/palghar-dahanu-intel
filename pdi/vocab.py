"""Controlled vocabularies shared by models, loaders and rules.

Everything here is deliberately explicit: stages, levels and micro-markets are the
backbone of the data-quality rules, so they live in one place.
"""

from django.db import models


class Category(models.TextChoices):
    INFRASTRUCTURE = "INFRASTRUCTURE", "Infrastructure"
    REAL_ESTATE = "REAL_ESTATE", "Real estate"
    INDUSTRIAL = "INDUSTRIAL", "Industrial"
    LOGISTICS = "LOGISTICS", "Logistics & warehousing"
    DIGITAL = "DIGITAL", "Digital infrastructure"
    UTILITIES = "UTILITIES", "Utilities"
    HOSPITALITY = "HOSPITALITY", "Hospitality"
    LAND = "LAND", "Land"
    REGULATORY = "REGULATORY", "Regulatory"


class Importance(models.TextChoices):
    HIGH = "HIGH", "High"
    MEDIUM = "MEDIUM", "Medium"
    LOW = "LOW", "Low"


class SourceLevel(models.TextChoices):
    PRIMARY = "PRIMARY", "Primary"
    SECONDARY = "SECONDARY", "Secondary"
    UNVERIFIED = "UNVERIFIED", "Unverified / reported"


# Lower rank = stronger evidence.
SOURCE_LEVEL_RANK = {"PRIMARY": 1, "SECONDARY": 2, "UNVERIFIED": 3}


class Stage(models.TextChoices):
    ANNOUNCED = "ANNOUNCED", "Announced"
    MOU = "MOU", "MoU signed"
    PROPOSAL = "PROPOSAL", "Proposal"
    DPR = "DPR", "DPR"
    APPROVAL = "APPROVAL", "Approved"
    LAND_IDENTIFIED = "LAND_IDENTIFIED", "Land identified"
    LAND_ACQUISITION = "LAND_ACQUISITION", "Land acquisition"
    LAND_ACQUIRED = "LAND_ACQUIRED", "Land acquired"
    TENDER = "TENDER", "Tender"
    TENDER_AWARDED = "TENDER_AWARDED", "Tender awarded"
    CONSTRUCTION_STARTED = "CONSTRUCTION_STARTED", "Construction started"
    UNDER_CONSTRUCTION = "UNDER_CONSTRUCTION", "Under construction"
    OPERATIONAL = "OPERATIONAL", "Operational"
    COMPLETED = "COMPLETED", "Completed"
    # Flags: they don't move a project along the lifecycle.
    DELAYED = "DELAYED", "Delayed"
    STALLED = "STALLED", "Stalled"
    CANCELLED = "CANCELLED", "Cancelled"
    REVIVED = "REVIVED", "Revived"
    NOTE = "NOTE", "Note (no stage change)"


# Lifecycle order. A project's current stage is the furthest stage supported by evidence.
STAGE_ORDER = {
    "ANNOUNCED": 10,
    "MOU": 15,
    "PROPOSAL": 20,
    "DPR": 30,
    "APPROVAL": 40,
    "LAND_IDENTIFIED": 50,
    "LAND_ACQUISITION": 55,
    "LAND_ACQUIRED": 60,
    "TENDER": 70,
    "TENDER_AWARDED": 75,
    "CONSTRUCTION_STARTED": 80,
    "UNDER_CONSTRUCTION": 85,
    "OPERATIONAL": 90,
    "COMPLETED": 95,
}
FLAG_STAGES = {"DELAYED", "STALLED", "CANCELLED", "REVIVED"}

# Coarse phases used for filters and dashboard tiles.
PHASES = {
    "PRE_APPROVAL": ("Announced / proposed", {"ANNOUNCED", "MOU", "PROPOSAL", "DPR"}),
    "APPROVED": ("Approved, pre-construction", {"APPROVAL", "LAND_IDENTIFIED", "LAND_ACQUISITION", "LAND_ACQUIRED", "TENDER", "TENDER_AWARDED"}),
    "CONSTRUCTION": ("Under construction", {"CONSTRUCTION_STARTED", "UNDER_CONSTRUCTION"}),
    "DONE": ("Operational / completed", {"OPERATIONAL", "COMPLETED"}),
}


def phase_of(stage):
    for key, (_label, stages) in PHASES.items():
        if stage in stages:
            return key
    return ""


class DatePrecision(models.TextChoices):
    DAY = "DAY", "Day"
    MONTH = "MONTH", "Month"
    YEAR = "YEAR", "Year"


class ReviewStatus(models.TextChoices):
    PENDING = "PENDING", "Pending review"
    APPROVED = "APPROVED", "Approved"
    REJECTED = "REJECTED", "Rejected"


class Origin(models.TextChoices):
    MANUAL = "MANUAL", "Manual entry"
    SEED = "SEED", "Seed research"
    INBOX = "INBOX", "From monitoring inbox"
    MAHARERA = "MAHARERA", "MahaRERA crawler"


class InvestmentBasis(models.TextChoices):
    SANCTIONED = "SANCTIONED", "Sanctioned / approved cost"
    ESTIMATED = "ESTIMATED", "Official estimate"
    REPORTED = "REPORTED", "Reported"
    MOU = "MOU", "MoU value (not an investment)"


class InvestmentScope(models.TextChoices):
    PROJECT = "PROJECT", "This project in Palghar district"
    WIDER = "WIDER", "Wider project / corridor beyond Palghar"


# Which figure represents a project when only one number can be shown/summed.
INVESTMENT_BASIS_PRIORITY = {"SANCTIONED": 1, "ESTIMATED": 2, "REPORTED": 3, "MOU": 4}


class FundingStage(models.TextChoices):
    ANNOUNCED = "ANNOUNCED", "Announced"
    COMMITTED = "COMMITTED", "Committed"
    APPROVED = "APPROVED", "Approved"
    DISBURSED = "DISBURSED", "Disbursed"
    COMPLETED = "COMPLETED", "Completed"


class FundingType(models.TextChoices):
    GOVERNMENT = "GOVERNMENT", "Government"
    BANK = "BANK", "Bank"
    NBFC = "NBFC", "NBFC"
    AIF = "AIF", "AIF"
    PE = "PE", "Private equity"
    CORPORATE = "CORPORATE", "Corporate"
    BOND = "BOND", "Bonds"
    PPP = "PPP", "PPP"
    MULTILATERAL = "MULTILATERAL", "Multilateral"
    OTHER = "OTHER", "Other"


class LandStatus(models.TextChoices):
    PROPOSED = "PROPOSED", "Proposed"
    NOTIFIED = "NOTIFIED", "Notified"
    UNDER_ACQUISITION = "UNDER_ACQUISITION", "Under acquisition"
    ACQUIRED = "ACQUIRED", "Acquired"
    ALLOTTED = "ALLOTTED", "Allotted"
    TRANSACTED = "TRANSACTED", "Transacted"
    DISPUTED = "DISPUTED", "Disputed"
    OTHER = "OTHER", "Other"


class RegulatoryType(models.TextChoices):
    RERA = "RERA", "MahaRERA"
    CRZ = "CRZ", "CRZ"
    ENVIRONMENTAL_CLEARANCE = "ENVIRONMENTAL_CLEARANCE", "Environmental clearance"
    FOREST = "FOREST", "Forest approval"
    LAND_ACQUISITION_NOTIFICATION = "LAND_ACQUISITION_NOTIFICATION", "Land acquisition notification"
    TOWN_PLANNING = "TOWN_PLANNING", "Town planning"
    ZONING = "ZONING", "Zoning"
    DEVELOPMENT_PLAN = "DEVELOPMENT_PLAN", "Development plan"
    GOVERNMENT_RESOLUTION = "GOVERNMENT_RESOLUTION", "Government resolution"
    COURT_ORDER = "COURT_ORDER", "Court order"
    DTEPA = "DTEPA", "DTEPA"
    PUBLIC_HEARING = "PUBLIC_HEARING", "Public hearing"
    LITIGATION = "LITIGATION", "Litigation"
    OTHER = "OTHER", "Other"


class RegulatoryStatus(models.TextChoices):
    APPLIED = "APPLIED", "Applied"
    PENDING = "PENDING", "Pending"
    GRANTED = "GRANTED", "Granted"
    REJECTED = "REJECTED", "Rejected"
    CHALLENGED = "CHALLENGED", "Challenged"
    STAYED = "STAYED", "Stayed"
    DISPOSED = "DISPOSED", "Disposed"
    OTHER = "OTHER", "Other"


class RelationshipType(models.TextChoices):
    PART_OF = "PART_OF", "Part of"
    CONNECTIVITY_FOR = "CONNECTIVITY_FOR", "Provides connectivity for"
    DRIVEN_BY = "DRIVEN_BY", "Driven by"
    SUPPLIES = "SUPPLIES", "Supplies"
    RELATED = "RELATED", "Related to"


class OrgType(models.TextChoices):
    DEVELOPER = "DEVELOPER", "Developer / promoter"
    COMPANY = "COMPANY", "Company"
    GOVERNMENT = "GOVERNMENT", "Government / authority"
    FINANCIER = "FINANCIER", "Financier / investor"
    CONTRACTOR = "CONTRACTOR", "Contractor"
    OTHER = "OTHER", "Other"


class OrgRole(models.TextChoices):
    PROMOTER = "PROMOTER", "Promoter / developer"
    AUTHORITY = "AUTHORITY", "Authority"
    CONTRACTOR = "CONTRACTOR", "Contractor"
    FINANCIER = "FINANCIER", "Financier"
    INVESTOR = "INVESTOR", "Investor"
    JV_PARTNER = "JV_PARTNER", "JV partner"
    OTHER = "OTHER", "Other"


TALUKAS = ["Palghar", "Vasai", "Dahanu", "Talasari", "Jawhar", "Mokhada", "Vikramgad", "Wada"]

MICRO_MARKETS = [
    "Palghar",
    "Boisar–Tarapur",
    "Murbe",
    "Saphale",
    "Manor",
    "Dahanu",
    "Vadhvan",
    "Gholvad–Bordi",
    "Vangaon",
    "Talasari",
    "Wada",
    "Vasai–Virar",
    "Jawhar–Mokhada–Vikramgad",
]
MICRO_MARKET_CHOICES = [(m, m) for m in MICRO_MARKETS]
TALUKA_CHOICES = [(t, t) for t in TALUKAS]

# Fallback micro-market when only the taluka is known.
TALUKA_DEFAULT_MARKET = {
    "Palghar": "Palghar",
    "Vasai": "Vasai–Virar",
    "Dahanu": "Dahanu",
    "Talasari": "Talasari",
    "Jawhar": "Jawhar–Mokhada–Vikramgad",
    "Mokhada": "Jawhar–Mokhada–Vikramgad",
    "Vikramgad": "Jawhar–Mokhada–Vikramgad",
    "Wada": "Wada",
}

# Activity dimensions used for micro-market intelligence (PRD §18).
ACTIVITY_DIMENSIONS = [
    ("rera", "RERA"),
    ("developer", "Developer / real estate"),
    ("industrial", "Industrial"),
    ("infrastructure", "Infrastructure"),
    ("land", "Land"),
    ("logistics", "Logistics & digital"),
    ("regulatory", "Regulatory"),
    ("funding", "Funding"),
]

NO_MATERIAL_TEXT = "No material verified development identified during the research period."
