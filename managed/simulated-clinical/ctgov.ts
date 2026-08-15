/**
 * ClinicalTrials.gov API v2 client.
 *
 * Free, no API key, JSON. This is the evidence spine of the node: every number
 * the recruitability engine emits traces back to an NCT id fetched here.
 *
 * The `asOf` parameter is what makes the retrospective demo honest — filtering
 * on StudyFirstPostDate means a query dated 2014 cannot see a trial registered
 * in 2016, so "using only 2014 data we ranked an indication approved in 2019"
 * is a real claim rather than a leaky one.
 */

const API = "https://clinicaltrials.gov/api/v2/studies";

const FIELDS = [
  "NCTId",
  "BriefTitle",
  "OverallStatus",
  "Phase",
  "StudyType",
  "Condition",
  "EnrollmentCount",
  "StartDate",
  "PrimaryCompletionDate",
  "StudyFirstPostDate",
  "WhyStopped",
  "EligibilityCriteria",
  "LocationCity",
  "PrimaryOutcomeTimeFrame",
].join(",");

export type TrialRecord = {
  conditions: string[];
  eligibilityCriteria?: string;
  enrollment?: number;
  firstPostDate?: string;
  nctId: string;
  phases: string[];
  primaryCompletionDate?: string;
  /** Free-text time frames of the primary outcomes, e.g. "At week 24". */
  primaryTimeFrames: string[];
  siteCount: number;
  startDate?: string;
  status: string;
  /** "INTERVENTIONAL" | "OBSERVATIONAL" | "EXPANDED_ACCESS". */
  studyType?: string;
  title: string;
  /** Populated only for TERMINATED / WITHDRAWN / SUSPENDED studies. */
  whyStopped?: string;
};

export type TrialQuery = {
  /** ISO date. Only studies first posted on or before this are returned. */
  asOf?: string;
  condition: string;
  intervention?: string;
  pageSize?: number;
  statuses?: string[];
};

type RawStudy = {
  protocolSection?: {
    conditionsModule?: { conditions?: string[] };
    contactsLocationsModule?: { locations?: unknown[] };
    designModule?: {
      enrollmentInfo?: { count?: number };
      phases?: string[];
      studyType?: string;
    };
    eligibilityModule?: { eligibilityCriteria?: string };
    identificationModule?: { briefTitle?: string; nctId?: string };
    outcomesModule?: { primaryOutcomes?: { timeFrame?: string }[] };
    statusModule?: {
      overallStatus?: string;
      primaryCompletionDateStruct?: { date?: string };
      startDateStruct?: { date?: string };
      studyFirstPostDateStruct?: { date?: string };
      whyStopped?: string;
    };
  };
};

function parseStudy(raw: RawStudy): TrialRecord {
  const p = raw.protocolSection ?? {};
  const status = p.statusModule ?? {};
  const design = p.designModule ?? {};

  return {
    conditions: p.conditionsModule?.conditions ?? [],
    eligibilityCriteria: p.eligibilityModule?.eligibilityCriteria,
    enrollment: design.enrollmentInfo?.count,
    firstPostDate: status.studyFirstPostDateStruct?.date,
    nctId: p.identificationModule?.nctId ?? "UNKNOWN",
    phases: design.phases ?? [],
    primaryCompletionDate: status.primaryCompletionDateStruct?.date,
    primaryTimeFrames: (p.outcomesModule?.primaryOutcomes ?? []).flatMap((o) =>
      o.timeFrame ? [o.timeFrame] : []
    ),
    siteCount: p.contactsLocationsModule?.locations?.length ?? 0,
    startDate: status.startDateStruct?.date,
    status: status.overallStatus ?? "UNKNOWN",
    studyType: design.studyType,
    title: p.identificationModule?.briefTitle ?? "",
    whyStopped: status.whyStopped,
  };
}

export async function searchTrials(
  q: TrialQuery
): Promise<{ total: number; trials: TrialRecord[] }> {
  const url = new URL(API);
  url.searchParams.set("query.cond", q.condition);
  url.searchParams.set("fields", FIELDS);
  url.searchParams.set("pageSize", String(q.pageSize ?? 50));
  url.searchParams.set("countTotal", "true");

  if (q.intervention) {
    url.searchParams.set("query.intr", q.intervention);
  }
  if (q.statuses?.length) {
    url.searchParams.set("filter.overallStatus", q.statuses.join(","));
  }
  if (q.asOf) {
    url.searchParams.set(
      "filter.advanced",
      `AREA[StudyFirstPostDate]RANGE[MIN,${q.asOf}]`
    );
  }

  const res = await fetch(url);
  if (!res.ok) {
    throw new Error(`ClinicalTrials.gov ${res.status}: ${await res.text()}`);
  }

  const body = (await res.json()) as {
    studies?: RawStudy[];
    totalCount?: number;
  };

  return {
    total: body.totalCount ?? 0,
    trials: (body.studies ?? []).map(parseStudy),
  };
}

/** One study by NCT id — same field set as `searchTrials`. */
export async function getTrial(nctId: string): Promise<TrialRecord> {
  const url = new URL(`${API}/${nctId}`);
  url.searchParams.set("fields", FIELDS);
  const res = await fetch(url);
  if (!res.ok) {
    throw new Error(
      `ClinicalTrials.gov ${res.status} for ${nctId}: ${await res.text()}`
    );
  }
  return parseStudy((await res.json()) as RawStudy);
}

// Registry prose writes durations both ways: "15 weeks" and "Week 24".
const VALUE_FIRST_RE = /(\d+(?:\.\d+)?)\s*(day|week|month|year)s?\b/gi;
const UNIT_FIRST_RE = /(day|week|month|year)s?\s*(\d+(?:\.\d+)?)/gi;
const MONTHS_PER_UNIT: Record<string, number> = {
  day: 1 / 30.4,
  month: 1,
  week: 1 / 4.345,
  year: 12,
};

function toMonths(value: string | undefined, unit: string | undefined): number {
  return Number(value ?? 0) * (MONTHS_PER_UNIT[unit?.toLowerCase() ?? ""] ?? 0);
}

/**
 * Longest duration mentioned across the primary-outcome time frames, in
 * months. "At week 24" → ~5.5; unparseable prose → 0. Used to split a
 * trial's registry window (start → primary completion) into enrolment time
 * vs endpoint follow-up.
 */
export function endpointWindowMonths(timeFrames: string[]): number {
  let max = 0;
  for (const tf of timeFrames) {
    for (const m of tf.matchAll(VALUE_FIRST_RE)) {
      max = Math.max(max, toMonths(m[1], m[2]));
    }
    for (const m of tf.matchAll(UNIT_FIRST_RE)) {
      max = Math.max(max, toMonths(m[2], m[1]));
    }
  }
  return max;
}

/**
 * Estimated months a trial spent ENROLLING. The registry's observable span
 * (start → primary completion) includes the last patient's endpoint window —
 * a 24-week-endpoint phase 3 "took 36 months" but only enrolled for ~30.
 * Floored at a third of the span: rolling long-endpoint designs (safety
 * studies whose endpoint IS the study duration) would otherwise go to zero.
 */
export function enrollmentMonths(
  windowMonths: number,
  timeFrames: string[]
): number {
  return Math.max(
    windowMonths - endpointWindowMonths(timeFrames),
    windowMonths / 3,
    1
  );
}

/** Whole months between two ISO dates; undefined if either is missing. */
export function monthsBetween(
  from: string | undefined,
  to: string | undefined
): number | undefined {
  if (!(from && to)) {
    return;
  }
  const a = new Date(from);
  const b = new Date(to);
  const months =
    (b.getFullYear() - a.getFullYear()) * 12 + (b.getMonth() - a.getMonth());
  return months > 0 ? months : undefined;
}

export function median(xs: number[]): number | undefined {
  if (xs.length === 0) {
    return;
  }
  const sorted = [...xs].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 === 0
    ? ((sorted[mid - 1] ?? 0) + (sorted[mid] ?? 0)) / 2
    : sorted[mid];
}
