"""Field map: which Form 990 / 990-EZ XML elements to extract.

Element names were checked against the Nonprofit Open Data Collective
Master Concordance File and against 2023v6.0-2025v4.0 returns. Paths are
matched by XML *local name*, relative to ``Return/ReturnData/<form>``, so
they are robust to namespace and schema-version changes.

Each entry maps an output key to ``(form part/line, element path)``.
"""

from __future__ import annotations

from typing import NamedTuple

FORM_990 = "IRS990"
FORM_990EZ = "IRS990EZ"
FORM_990PF = "IRS990PF"

FORM_ELEMENTS = {"990": FORM_990, "990EZ": FORM_990EZ, "990PF": FORM_990PF}

# Core totals, keyed by ProPublica Nonprofit Explorer names so existing
# fossfoundation reports keep working.
CORE: dict[str, dict[str, str]] = {
    FORM_990: {
        "totrevenue": "CYTotalRevenueAmt",
        "totfuncexpns": "CYTotalExpensesAmt",
        "totcntrbgfts": "CYContributionsGrantsAmt",
        "totprgmrevnue": "CYProgramServiceRevenueAmt",
        "invstmntinc": "CYInvestmentIncomeAmt",
        "totassetsend": "TotalAssetsEOYAmt",
        "totliabend": "TotalLiabilitiesEOYAmt",
        "totnetassetend": "NetAssetsOrFundBalancesEOYAmt",
    },
    FORM_990EZ: {
        "totrevenue": "TotalRevenueAmt",
        "totfuncexpns": "TotalExpensesAmt",
        "totcntrbgfts": "ContributionsGiftsGrantsEtcAmt",
        "totprgmrevnue": "ProgramServiceRevenueAmt",
        "invstmntinc": "InvestmentIncomeAmt",
        "totassetsend": "Form990TotalAssetsGrp/EOYAmt",
        "totliabend": "SumOfTotalLiabilitiesGrp/EOYAmt",
        "totnetassetend": "NetAssetsOrFundBalancesEOYAmt",
    },
}

# Single-value fields (P1). Value type is inferred from the name suffix:
# *Amt / *Cnt -> int, *Ind -> bool, otherwise text.
SCALARS: dict[str, dict[str, tuple[str, str]]] = {
    FORM_990: {
        "employees": ("I-5", "TotalEmployeeCnt"),
        "volunteers": ("I-6", "TotalVolunteersCnt"),
        "board_voting_members": ("VI-1a", "GoverningBodyVotingMembersCnt"),
        "board_independent_members": ("VI-1b", "IndependentVotingMemberCnt"),
        "has_members": ("VI-6", "MembersOrStockholdersInd"),
        "members_elect_board": ("VI-7a", "ElectionOfBoardMembersInd"),
        "contractors_over_100k": ("VII-B-2", "CntrctRcvdGreaterThan100KCnt"),
        "officers_comp_from_org": (
            "VII-1d(D)",
            "TotalReportableCompFromOrgAmt",
        ),
        "officers_comp_from_related": (
            "VII-1d(E)",
            "TotReportableCompRltdOrgAmt",
        ),
        "officers_other_comp": ("VII-1d(F)", "TotalOtherCompensationAmt"),
        "individuals_over_100k": ("VII-2", "IndivRcvdGreaterThan100KCnt"),
        "former_officers_listed": ("VII-3", "FormerOfcrEmployeesListedInd"),
        "any_comp_over_150k": ("VII-4", "TotalCompGreaterThan150KInd"),
        "comp_from_unrelated_source": (
            "VII-5",
            "CompensationFromOtherSrcsInd",
        ),
        "federated_campaigns": ("VIII-1a", "FederatedCampaignsAmt"),
        "membership_dues": ("VIII-1b", "MembershipDuesAmt"),
        "fundraising_events": ("VIII-1c", "FundraisingAmt"),
        "related_orgs": ("VIII-1d", "RelatedOrganizationsAmt"),
        "government_grants": ("VIII-1e", "GovernmentGrantsAmt"),
        "other_contributions": ("VIII-1f", "AllOtherContributionsAmt"),
        "noncash_contributions": ("VIII-1g", "NoncashContributionsAmt"),
        "total_contributions": ("VIII-1h", "TotalContributionsAmt"),
        "total_program_revenue": ("VIII-2g", "TotalProgramServiceRevenueAmt"),
    },
    FORM_990EZ: {
        "membership_dues": ("EZ-I-3", "MembershipDuesAmt"),
    },
}

# Part IX functional expense lines: (line, group element). Each group has
# Total / Program services / Management & general / Fundraising columns.
FUNCTIONAL_EXPENSES: dict[str, tuple[str, str]] = {
    "grants_domestic_orgs": ("IX-1", "GrantsToDomesticOrgsGrp"),
    "grants_domestic_individuals": ("IX-2", "GrantsToDomesticIndividualsGrp"),
    "grants_foreign": ("IX-3", "ForeignGrantsGrp"),
    "officer_compensation": ("IX-5", "CompCurrentOfcrDirectorsGrp"),
    "other_salaries": ("IX-7", "OtherSalariesAndWagesGrp"),
    "fees_management": ("IX-11a", "FeesForServicesManagementGrp"),
    "fees_legal": ("IX-11b", "FeesForServicesLegalGrp"),
    "fees_accounting": ("IX-11c", "FeesForServicesAccountingGrp"),
    "fees_lobbying": ("IX-11d", "FeesForServicesLobbyingGrp"),
    "fees_prof_fundraising": ("IX-11e", "FeesForServicesProfFundraising"),
    "fees_investment_mgmt": ("IX-11f", "FeesForSrvcInvstMgmntFeesGrp"),
    "fees_other": ("IX-11g", "FeesForServicesOtherGrp"),
    "advertising": ("IX-12", "AdvertisingGrp"),
    "office": ("IX-13", "OfficeExpensesGrp"),
    "information_technology": ("IX-14", "InformationTechnologyGrp"),
    "occupancy": ("IX-16", "OccupancyGrp"),
    "travel": ("IX-17", "TravelGrp"),
    "conferences": ("IX-19", "ConferencesMeetingsGrp"),
    "total": ("IX-25", "TotalFunctionalExpensesGrp"),
}

# Output column -> accepted child element names (older schemas used the
# names without the "Amt" suffix in a few groups).
FUNCTIONAL_COLUMNS: dict[str, tuple[str, ...]] = {
    "total": ("TotalAmt", "Total"),
    "program": ("ProgramServicesAmt", "ProgramServices"),
    "management": ("ManagementAndGeneralAmt", "ManagementAndGeneral"),
    "fundraising": ("FundraisingAmt", "Fundraising"),
}

# Part X balance sheet lines with beginning/end of year columns.
BALANCE_SHEET: dict[str, tuple[str, str]] = {
    "cash": ("X-1", "CashNonInterestBearingGrp"),
    "savings": ("X-2", "SavingsAndTempCashInvstGrp"),
    "investments_public": ("X-11", "InvestmentsPubTradedSecGrp"),
    "total_assets": ("X-16", "TotalAssetsGrp"),
    "deferred_revenue": ("X-19", "DeferredRevenueGrp"),
    "total_liabilities": ("X-26", "TotalLiabilitiesGrp"),
    "net_assets_unrestricted": ("X-27", "NoDonorRestrictionNetAssetsGrp"),
    "net_assets_restricted": ("X-28", "DonorRestrictionNetAssetsGrp"),
}

BALANCE_COLUMNS: dict[str, tuple[str, ...]] = {
    "boy": ("BOYAmt",),
    "eoy": ("EOYAmt",),
}

# Single values in schedules, relative to ``Return/ReturnData``.
SCHEDULE_SCALARS: dict[str, tuple[str, str]] = {
    "grant_records_maintained": (
        "I-I-1",
        "IRS990ScheduleI/GrantRecordsMaintainedInd",
    ),
    "grants_501c3_org_count": ("I-II-2", "IRS990ScheduleI/Total501c3OrgCnt"),
    "grants_other_org_count": ("I-II-3", "IRS990ScheduleI/TotalOtherOrgCnt"),
}


class Table(NamedTuple):
    """A repeating group (one row per element) to extract as a table.

    Attributes:
        line: Form part/line reference, for documentation.
        parent: Element under ``Return/ReturnData`` holding the group,
            e.g. ``IRS990`` or ``IRS990ScheduleR``.
        group: Local name of the repeating element.
        columns: Output column -> candidate child paths (first found wins).
        address: Path prefix of the row's address container ("" if
            ``USAddress``/``ForeignAddress`` are direct children), or None.
            Only city, state/province and country are kept, never street.
        person_name: Path whose presence marks the row as an individual,
            whose name is withheld unless explicitly requested.
        business_flag: Checkbox path that must be checked for a row
            without ``person_name`` to count as a business. Rows without
            it are treated as individuals, because some filers put
            people's names in ``BusinessName``. None means any row
            without ``person_name`` is a business.
        checkboxes: True if absent ``*Ind`` columns mean "unchecked"
            (False) rather than "not reported" (None).

    """

    line: str
    parent: str
    group: str
    columns: dict[str, tuple[str, ...]]
    address: str | None = None
    person_name: str | None = None
    business_flag: str | None = None
    checkboxes: bool = False


_NAME = "BusinessNameLine1Txt"
_ORG_COLUMNS: dict[str, tuple[str, ...]] = {
    "ein": ("EIN",),
    "activity": ("PrimaryActivitiesTxt",),
    "domicile_state": ("LegalDomicileStateCd",),
    "domicile_country": ("LegalDomicileForeignCountryCd",),
    "controlling_entity": (
        f"DirectControllingEntityName/{_NAME}",
        "DirectControllingNACd",
    ),
}

TABLES: dict[str, Table] = {
    "program_service_revenue": Table(
        "VIII-2a-f",
        FORM_990,
        "ProgramServiceRevenueGrp",
        {
            "description": ("Desc",),
            "business_code": ("BusinessCd",),
            "total": ("TotalRevenueColumnAmt",),
            "related_or_exempt": ("RelatedOrExemptFuncIncomeAmt",),
            "unrelated_business": ("UnrelatedBusinessRevenueAmt",),
            "excluded": ("ExclusionAmt",),
        },
    ),
    "other_expenses": Table(
        "IX-24a-e",
        FORM_990,
        "OtherExpensesGrp",
        {
            "description": ("Desc",),
            "total": ("TotalAmt",),
            "program": ("ProgramServicesAmt",),
            "management": ("ManagementAndGeneralAmt",),
            "fundraising": ("FundraisingAmt",),
        },
    ),
    "officers": Table(
        "VII-A-1a",
        FORM_990,
        "Form990PartVIISectionAGrp",
        {
            "name": ("PersonNm", f"BusinessName/{_NAME}"),
            "title": ("TitleTxt",),
            "hours_per_week": ("AverageHoursPerWeekRt",),
            "hours_per_week_related": ("AverageHoursPerWeekRltdOrgRt",),
            "trustee_or_director": ("IndividualTrusteeOrDirectorInd",),
            "institutional_trustee": ("InstitutionalTrusteeInd",),
            "officer": ("OfficerInd",),
            "key_employee": ("KeyEmployeeInd",),
            "highest_compensated": ("HighestCompensatedEmployeeInd",),
            "former": ("FormerOfcrDirectorTrusteeInd",),
            "comp_from_org": ("ReportableCompFromOrgAmt",),
            "comp_from_related": ("ReportableCompFromRltdOrgAmt",),
            "other_comp": ("OtherCompensationAmt",),
        },
        person_name="PersonNm",
        business_flag="InstitutionalTrusteeInd",
        checkboxes=True,
    ),
    "contractors": Table(
        "VII-B-1",
        FORM_990,
        "ContractorCompensationGrp",
        {
            "name": (
                f"ContractorName/BusinessName/{_NAME}",
                "ContractorName/PersonNm",
            ),
            "services": ("ServicesDesc",),
            "compensation": ("CompensationAmt",),
        },
        address="ContractorAddress",
        person_name="ContractorName/PersonNm",
    ),
    "grants_to_orgs": Table(
        "I-II",
        "IRS990ScheduleI",
        "RecipientTable",
        {
            "name": (f"RecipientBusinessName/{_NAME}",),
            "ein": ("RecipientEIN",),
            "irc_section": ("IRCSectionDesc",),
            "cash": ("CashGrantAmt",),
            "noncash": ("NonCashAssistanceAmt",),
            "noncash_description": ("NonCashAssistanceDesc",),
            "valuation_method": ("ValuationMethodUsedDesc",),
            "purpose": ("PurposeOfGrantTxt",),
        },
        address="",
    ),
    "grants_to_individuals": Table(
        "I-III",
        "IRS990ScheduleI",
        "GrantsOtherAsstToIndivInUSGrp",
        {
            "grant_type": ("GrantTypeTxt",),
            "recipients": ("RecipientCnt",),
            "cash": ("CashGrantAmt",),
            "noncash": ("NonCashAssistanceAmt",),
            "noncash_description": ("NonCashAssistanceDesc",),
            "valuation_method": ("ValuationMethodUsedDesc",),
        },
    ),
    "related_disregarded": Table(
        "R-I",
        "IRS990ScheduleR",
        "IdDisregardedEntitiesGrp",
        {
            "name": (f"DisregardedEntityName/{_NAME}",),
            **_ORG_COLUMNS,
            "total_income": ("TotalIncomeAmt",),
            "eoy_assets": ("EndOfYearAssetsAmt",),
        },
        address="",
    ),
    "related_tax_exempt": Table(
        "R-II",
        "IRS990ScheduleR",
        "IdRelatedTaxExemptOrgGrp",
        {
            # The IRS schema names this column DisregardedEntityName.
            "name": (
                f"DisregardedEntityName/{_NAME}",
                f"RelatedOrganizationName/{_NAME}",
            ),
            **_ORG_COLUMNS,
            "exempt_section": ("ExemptCodeSectionTxt",),
            "public_charity_status": ("PublicCharityStatusTxt",),
            "controlled": ("ControlledOrganizationInd",),
        },
        address="",
    ),
    "related_partnerships": Table(
        "R-III",
        "IRS990ScheduleR",
        "IdRelatedOrgTxblPartnershipGrp",
        {
            "name": (f"RelatedOrganizationName/{_NAME}",),
            **_ORG_COLUMNS,
            "predominant_income": ("PredominantIncomeTypeTxt",),
            "share_of_income": ("ShareOfTotalIncomeAmt",),
            "share_of_eoy_assets": ("ShareOfEOYAssetsAmt",),
            "disproportionate_allocations": (
                "DisproportionateAllocationsInd",
            ),
            "general_partner": ("GeneralOrManagingPartnerInd",),
            "ownership_pct": ("OwnershipPct",),
        },
        address="",
    ),
    "related_corporations": Table(
        "R-IV",
        "IRS990ScheduleR",
        "IdRelatedOrgTxblCorpTrGrp",
        {
            "name": (f"RelatedOrganizationName/{_NAME}",),
            **_ORG_COLUMNS,
            "entity_type": ("EntityTypeTxt",),
            "share_of_income": ("ShareOfTotalIncomeAmt",),
            "share_of_eoy_assets": ("ShareOfEOYAssetsAmt",),
            "ownership_pct": ("OwnershipPct",),
            "controlled": ("ControlledOrganizationInd",),
        },
        address="",
    ),
    "related_transactions": Table(
        "R-V-2",
        "IRS990ScheduleR",
        "TransactionsRelatedOrgGrp",
        {
            "other_org": (f"OtherOrganizationName/{_NAME}",),
            # Letter code a-s from Schedule R Part V line 1.
            "transaction_type": ("TransactionTypeTxt",),
            "amount": ("InvolvedAmt",),
            "method": ("MethodOfAmountDeterminationTxt",),
        },
    ),
}

SCHEDULES = ("IRS990ScheduleI", "IRS990ScheduleR")
"""Schedules whose presence is reported as ``has_schedule_*`` flags."""
