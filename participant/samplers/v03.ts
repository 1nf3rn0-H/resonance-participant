import type {
  AnalysisWindow,
  AnomalyFeature,
  AnomalySignal,
  Baseline,
  CandidateReasonCode,
  DetectorOutputs,
  Episode,
  ListeningEvent,
  ModeTransitionOutput,
  PersistentTrackIntentionalityOutput,
  Session,
  SessionDeviationOutput,
} from './types'

export const ANOMALY_DETECTOR_VERSION = 'music-episode-surfacing-0.3.0'
export const ANOMALY_BASELINE_POLICY = 'frozen-prewindow-within-participant-v2'
export const ANOMALY_THRESHOLD = 0

const SESSION_GAP_MS = 30 * 60_000
const DAY_MS = 24 * 60 * 60_000
const MIN_SESSION_EVENTS = 5
const MIN_SESSION_MINUTES = 10
const MIN_TRACK_PLAYS = 10
const MAX_EPISODES = 10

type AnalysisOptions = {
  maxEpisodes?: number
  listenerBaseline?: Pick<Baseline, 'replayTrack' | 'replayPart'>
  baselineEventIds?: ReadonlySet<string>
}

type SessionFeatures = {
  session: Session
  items: ListeningEvent[]
  events: number
  uniqueTracks: number
  uniqueArtists: number
  playedMin: number
  skipRate: number | null
  completeRate: number | null
  manualStartRate: number | null
  explicitNavigationRate: number | null
  shuffleRate: number | null
  maxTrackRepeats: number
  repeatExcess: number
  topTrackShare: number
  backbtnCount: number | null
  clickrowCount: number | null
  fwdbtnCount: number | null
}

type PercentileFeatures = {
  playedMin: number
  skipRate: number | null
  manualStartRate: number | null
  maxTrackRepeats: number
  repeatExcess: number
  topTrackShare: number
  backbtnCount: number | null
  clickrowCount: number | null
}

type DailyFeatures = {
  date: string
  items: ListeningEvent[]
  events: number
  playedMin: number
  skipRate: number | null
  manualRate: number | null
  uniqueTracks: number
  topTrackPlays: number
  topTrackShare: number
  repeatExcess: number
  diversity: number
}

export function anomalyBaselineMultiplier(selectedDays: number) {
  return selectedDays <= 30 ? 4 : 2
}

export function selectAnalysisScope(input: ListeningEvent[], window: AnalysisWindow) {
  const events = [...input].sort((a, b) => Date.parse(a.occurredAt) - Date.parse(b.occurredAt))
  if (!events.length) return { selected: [], baseline: [], analysis: [], multiplier: 1, frozen: false }

  const latest = Date.parse(events.at(-1)!.occurredAt)
  let selected: ListeningEvent[]
  let selectedDays: number
  let selectedEnd = latest
  let selectedStart: number

  if (window.mode === 'ALL') return { selected: events, baseline: events, analysis: events, multiplier: 1, frozen: false }
  if (window.mode === 'CUSTOM') {
    const start = window.start ? Date.parse(`${window.start}T00:00:00.000Z`) : -Infinity
    const end = window.end ? Date.parse(`${window.end}T23:59:59.999Z`) : Infinity
    selected = events.filter(event => {
      const occurredAt = Date.parse(event.occurredAt)
      return occurredAt >= start && occurredAt <= end
    })
    if (!selected.length) return { selected: [], baseline: [], analysis: [], multiplier: 1, frozen: false }
    selectedStart = Number.isFinite(start) ? start : Date.parse(selected[0].occurredAt)
    selectedEnd = Number.isFinite(end) ? end : Date.parse(selected.at(-1)!.occurredAt)
    selectedDays = Math.max(1, (selectedEnd - selectedStart) / DAY_MS)
  } else {
    selectedDays = window.mode === 'LAST_7' ? 7 : window.mode === 'LAST_30' ? 30 : 90
    selectedStart = latest - selectedDays * DAY_MS
    selected = events.filter(event => {
      const occurredAt = Date.parse(event.occurredAt)
      return occurredAt >= selectedStart && occurredAt <= latest
    })
  }

  const multiplier = anomalyBaselineMultiplier(selectedDays)
  const baselineStart = selectedStart - selectedDays * multiplier * DAY_MS
  const baseline = events.filter(event => {
    const occurredAt = Date.parse(event.occurredAt)
    return occurredAt >= baselineStart && occurredAt < selectedStart
  })
  const analysis = [...baseline, ...selected].sort((a, b) => Date.parse(a.occurredAt) - Date.parse(b.occurredAt))
  return { selected, baseline, analysis, multiplier, frozen: true }
}

const round = (value: number, digits = 3) => Number(value.toFixed(digits))
const normalize = (value: string) => value.normalize('NFKC').toLocaleLowerCase().replace(/[^\p{L}\p{N}]+/gu, ' ').trim()
const trackKey = (event: ListeningEvent) => event.providerTrackId
  ? `${event.provider}:${event.providerTrackId}`
  : `${event.provider}:fallback:${normalize(event.artistName)}||${normalize(event.trackName)}`
const dayKey = (iso: string) => iso.slice(0, 10)
const hasReason = (event: ListeningEvent) => event.startReason !== null && event.startReason.trim() !== ''
const startReason = (event: ListeningEvent) => event.startReason?.toLocaleLowerCase() ?? ''
const manualStart = (event: ListeningEvent) => ['clickrow', 'playbtn', 'backbtn'].includes(startReason(event))
const explicitNavigation = (event: ListeningEvent) => ['clickrow', 'playbtn', 'backbtn', 'fwdbtn'].includes(startReason(event))
const completed = (event: ListeningEvent) => event.endReason?.toLocaleLowerCase() === 'trackdone'

function nullableRate<T>(items: T[], available: (item: T) => boolean, positive: (item: T) => boolean) {
  const observed = items.filter(available)
  return observed.length ? observed.filter(positive).length / observed.length : null
}

function percentileRank(value: number | null, values: Array<number | null>) {
  if (value === null) return null
  const observed = values.filter((item): item is number => item !== null && Number.isFinite(item))
  if (!observed.length) return null
  const below = observed.filter(item => item < value).length
  const equal = observed.filter(item => item === value).length
  return (below + equal / 2) / observed.length
}

function weighted(components: Array<[number | null, number]>) {
  const available = components.filter((item): item is [number, number] => item[0] !== null)
  const totalWeight = available.reduce((sum, [, weight]) => sum + weight, 0)
  return totalWeight ? available.reduce((sum, [value, weight]) => sum + value * weight, 0) / totalWeight : null
}

function sessionize(events: ListeningEvent[], idPrefix = 'session') {
  const sessions: Session[] = []
  let current: Session | undefined
  for (const event of events) {
    if (!current || Date.parse(event.occurredAt) - Date.parse(current.endedAt) > SESSION_GAP_MS) {
      current = {
        id: `${idPrefix}-${sessions.length + 1}`,
        startedAt: event.occurredAt,
        endedAt: event.occurredAt,
        eventIds: [],
      }
      sessions.push(current)
    }
    current.endedAt = event.occurredAt
    current.eventIds.push(event.id)
    event.sessionId = current.id
  }
  return sessions
}

function sessionFeatures(session: Session, items: ListeningEvent[]): SessionFeatures {
  const trackCounts = new Map<string, { event: ListeningEvent; count: number }>()
  for (const item of items) {
    const key = trackKey(item)
    const prior = trackCounts.get(key)
    trackCounts.set(key, { event: prior?.event ?? item, count: (prior?.count ?? 0) + 1 })
  }
  const top = [...trackCounts.values()].sort((a, b) => b.count - a.count)[0]
  const reasonAvailable = items.some(hasReason)
  return {
    session,
    items,
    events: items.length,
    uniqueTracks: trackCounts.size,
    uniqueArtists: new Set(items.map(item => normalize(item.artistName))).size,
    playedMin: items.reduce((sum, item) => sum + item.millisecondsPlayed, 0) / 60_000,
    skipRate: nullableRate(items, item => item.skipped !== null, item => item.skipped === true),
    completeRate: nullableRate(items, item => item.endReason !== null, completed),
    manualStartRate: reasonAvailable ? items.filter(manualStart).length / items.length : null,
    explicitNavigationRate: reasonAvailable ? items.filter(explicitNavigation).length / items.length : null,
    shuffleRate: nullableRate(items, item => item.shuffle !== null, item => item.shuffle === true),
    maxTrackRepeats: top.count,
    repeatExcess: items.length - trackCounts.size,
    topTrackShare: top.count / items.length,
    backbtnCount: reasonAvailable ? items.filter(item => startReason(item) === 'backbtn').length : null,
    clickrowCount: reasonAvailable ? items.filter(item => startReason(item) === 'clickrow').length : null,
    fwdbtnCount: reasonAvailable ? items.filter(item => startReason(item) === 'fwdbtn').length : null,
  }
}

function percentilesFor(profile: SessionFeatures, profiles: SessionFeatures[]): PercentileFeatures {
  return {
    playedMin: percentileRank(profile.playedMin, profiles.map(item => item.playedMin))!,
    skipRate: percentileRank(profile.skipRate, profiles.map(item => item.skipRate)),
    manualStartRate: percentileRank(profile.manualStartRate, profiles.map(item => item.manualStartRate)),
    maxTrackRepeats: percentileRank(profile.maxTrackRepeats, profiles.map(item => item.maxTrackRepeats))!,
    repeatExcess: percentileRank(profile.repeatExcess, profiles.map(item => item.repeatExcess))!,
    topTrackShare: percentileRank(profile.topTrackShare, profiles.map(item => item.topTrackShare))!,
    backbtnCount: percentileRank(profile.backbtnCount, profiles.map(item => item.backbtnCount)),
    clickrowCount: percentileRank(profile.clickrowCount, profiles.map(item => item.clickrowCount)),
  }
}

function sessionReasonCodes(profile: SessionFeatures, pct: PercentileFeatures): CandidateReasonCode[] {
  const codes: CandidateReasonCode[] = []
  if (pct.maxTrackRepeats >= 0.9) codes.push('EXTREME_TRACK_REPETITION')
  if (pct.topTrackShare >= 0.9) codes.push('HIGH_TRACK_CONCENTRATION')
  if (pct.manualStartRate !== null && pct.manualStartRate >= 0.9) codes.push('HIGH_MANUAL_SELECTION')
  if (pct.backbtnCount !== null && pct.backbtnCount >= 0.9 && (profile.backbtnCount ?? 0) > 0) codes.push('BACK_NAVIGATION')
  if (pct.skipRate !== null && pct.skipRate >= 0.9) codes.push('HIGH_SKIP_EXPLORATION')
  if (pct.skipRate !== null && pct.skipRate <= 0.1) codes.push('UNUSUALLY_LOW_SKIP')
  if (pct.playedMin >= 0.9) codes.push('LONG_SESSION')
  return codes
}

function computeSessionDeviations(profiles: SessionFeatures[], referenceProfiles: SessionFeatures[], surfaced: ReadonlySet<string> | undefined) {
  if (!referenceProfiles.length) return []
  return profiles
    .filter(profile => (!surfaced || profile.session.eventIds.every(id => surfaced.has(id))) && profile.events >= MIN_SESSION_EVENTS && profile.playedMin >= MIN_SESSION_MINUTES)
    .map((profile, index): SessionDeviationOutput => {
      const pct = percentilesFor(profile, referenceProfiles)
      const repeatSignal = weighted([[pct.maxTrackRepeats, 0.45], [pct.repeatExcess, 0.25], [pct.topTrackShare, 0.30]])!
      const activeSignal = weighted([[pct.manualStartRate, 0.60], [pct.backbtnCount, 0.20], [pct.clickrowCount, 0.20]])
      const persistenceSignal = weighted([[pct.playedMin, 0.60], [pct.skipRate === null ? null : 1 - pct.skipRate, 0.40]])
      const skipExtremeScore = pct.skipRate === null ? null : 2 * Math.abs(pct.skipRate - 0.5)
      const deviationScore = weighted([[repeatSignal, 0.35], [activeSignal, 0.30], [persistenceSignal, 0.20], [skipExtremeScore, 0.15]])!
      return {
        id: `session-deviation-${index + 1}`,
        sessionId: profile.session.id,
        startedAt: profile.session.startedAt,
        endedAt: profile.session.endedAt,
        eventIds: profile.session.eventIds,
        deviationScore: round(deviationScore),
        repeatSignal: round(repeatSignal),
        activeSignal: activeSignal === null ? null : round(activeSignal),
        persistenceSignal: persistenceSignal === null ? null : round(persistenceSignal),
        skipExtremeScore: skipExtremeScore === null ? null : round(skipExtremeScore),
        features: {
          events: profile.events,
          unique_tracks: profile.uniqueTracks,
          unique_artists: profile.uniqueArtists,
          played_min: round(profile.playedMin),
          skip_rate: profile.skipRate === null ? null : round(profile.skipRate),
          complete_rate: profile.completeRate === null ? null : round(profile.completeRate),
          manual_start_rate: profile.manualStartRate === null ? null : round(profile.manualStartRate),
          explicit_navigation_rate: profile.explicitNavigationRate === null ? null : round(profile.explicitNavigationRate),
          shuffle_rate: profile.shuffleRate === null ? null : round(profile.shuffleRate),
          max_track_repeats: profile.maxTrackRepeats,
          repeat_excess: profile.repeatExcess,
          top_track_share: round(profile.topTrackShare),
          backbtn_count: profile.backbtnCount,
          clickrow_count: profile.clickrowCount,
          fwdbtn_count: profile.fwdbtnCount,
        },
        percentiles: Object.fromEntries(Object.entries(pct).map(([key, value]) => [key, value === null ? null : round(value)])),
        reasonCodes: sessionReasonCodes(profile, pct),
        detectorVersion: ANOMALY_DETECTOR_VERSION,
      }
    })
    .sort((a, b) => b.deviationScore - a.deviationScore)
}

function computePersistentTracks(events: ListeningEvent[], baselineEventIds: ReadonlySet<string> | undefined, surfaced: ReadonlySet<string> | undefined) {
  const groups = new Map<string, ListeningEvent[]>()
  for (const event of events) groups.set(trackKey(event), [...(groups.get(trackKey(event)) ?? []), event])
  const eligible = [...groups.entries()]
    .map(([key, allItems]) => ({ key, allItems, profileItems: baselineEventIds ? allItems.filter(item => baselineEventIds.has(item.id)) : allItems }))
    .filter(({ allItems, profileItems }) => profileItems.length >= MIN_TRACK_PLAYS && (!surfaced || allItems.some(item => surfaced.has(item.id))))
  const manualRates = eligible.map(({ profileItems }) => nullableRate(profileItems, hasReason, manualStart)).filter((value): value is number => value !== null).sort((a, b) => a - b)
  const highAgencyCutoff = manualRates.length ? manualRates[Math.floor((manualRates.length - 1) * 0.75)] : 1

  return eligible.map(({ key, allItems, profileItems }, index): PersistentTrackIntentionalityOutput => {
    const ordered = [...profileItems].sort((a, b) => Date.parse(a.occurredAt) - Date.parse(b.occurredAt))
    const exemplar = ordered[0]
    const skipRate = nullableRate(profileItems, item => item.skipped !== null, item => item.skipped === true)
    const manualRate = nullableRate(profileItems, hasReason, manualStart)
    const completeRate = nullableRate(profileItems, item => item.endReason !== null, completed)
    const dayCounts = new Map<string, number>()
    for (const item of profileItems) dayCounts.set(dayKey(item.occurredAt), (dayCounts.get(dayKey(item.occurredAt)) ?? 0) + 1)
    const maxDayPlays = Math.max(...dayCounts.values())
    const score = manualRate === null || skipRate === null ? null : manualRate * (1 - skipRate) * Math.log1p(profileItems.length)
    const classification = manualRate !== null && skipRate !== null && manualRate <= 0.15 && skipRate <= 0.20
      ? 'PASSIVE_REPEAT'
      : manualRate !== null && score !== null && manualRate >= Math.max(0.15, highAgencyCutoff)
        ? 'HIGH_AGENCY_REPEAT'
        : 'PERSISTENT_TRACK'
    const reasonCodes: CandidateReasonCode[] = [classification === 'PASSIVE_REPEAT' ? 'PASSIVE_REPEAT' : classification === 'HIGH_AGENCY_REPEAT' ? 'HIGH_AGENCY_REPEAT' : 'MULTI_DAY_RECURRENCE']
    if (dayCounts.size > 1) reasonCodes.push('MULTI_DAY_RECURRENCE')
    return {
      id: `track-intentionality-${index + 1}`,
      trackKey: key,
      providerTrackId: exemplar.providerTrackId ?? null,
      trackName: exemplar.trackName,
      artistName: exemplar.artistName,
      albumName: exemplar.albumName,
      plays: profileItems.length,
      totalMinutes: round(profileItems.reduce((sum, item) => sum + item.millisecondsPlayed, 0) / 60_000),
      skipRate: skipRate === null ? null : round(skipRate),
      manualRate: manualRate === null ? null : round(manualRate),
      completeRate: completeRate === null ? null : round(completeRate),
      firstPlay: ordered[0].occurredAt,
      lastPlay: ordered.at(-1)!.occurredAt,
      activeDays: dayCounts.size,
      maxDayPlays,
      burstShare: round(maxDayPlays / profileItems.length),
      agencyPersistenceScore: score === null ? null : round(score),
      classification,
      eventIds: allItems.filter(item => !surfaced || surfaced.has(item.id)).map(item => item.id),
      reasonCodes: [...new Set(reasonCodes)],
      detectorVersion: ANOMALY_DETECTOR_VERSION,
    }
  }).sort((a, b) => (b.agencyPersistenceScore ?? -1) - (a.agencyPersistenceScore ?? -1) || b.plays - a.plays)
}

function dailyFeatures(events: ListeningEvent[]) {
  const groups = new Map<string, ListeningEvent[]>()
  for (const event of events) groups.set(dayKey(event.occurredAt), [...(groups.get(dayKey(event.occurredAt)) ?? []), event])
  return [...groups.entries()].sort(([a], [b]) => a.localeCompare(b)).map(([date, items]): DailyFeatures => {
    const trackCounts = new Map<string, number>()
    for (const item of items) trackCounts.set(trackKey(item), (trackCounts.get(trackKey(item)) ?? 0) + 1)
    const topTrackPlays = Math.max(...trackCounts.values())
    return {
      date,
      items,
      events: items.length,
      playedMin: items.reduce((sum, item) => sum + item.millisecondsPlayed, 0) / 60_000,
      skipRate: nullableRate(items, item => item.skipped !== null, item => item.skipped === true),
      manualRate: nullableRate(items, hasReason, manualStart),
      uniqueTracks: trackCounts.size,
      topTrackPlays,
      topTrackShare: topTrackPlays / items.length,
      repeatExcess: items.length - trackCounts.size,
      diversity: trackCounts.size / items.length,
    }
  })
}

function dailyRecord(day: DailyFeatures): Record<string, number | null> {
  return {
    events: day.events,
    played_min: round(day.playedMin),
    skip_rate: day.skipRate === null ? null : round(day.skipRate),
    manual_rate: day.manualRate === null ? null : round(day.manualRate),
    unique_tracks: day.uniqueTracks,
    top_track_plays: day.topTrackPlays,
    top_track_share: round(day.topTrackShare),
    repeat_excess: day.repeatExcess,
    diversity: round(day.diversity),
  }
}

function computeModeTransitions(events: ListeningEvent[], surfaced: ReadonlySet<string> | undefined) {
  const days = dailyFeatures(events)
  const outputs: ModeTransitionOutput[] = []
  for (let index = 1; index < days.length; index++) {
    const from = days[index - 1]
    const to = days[index]
    if (from.skipRate === null || to.skipRate === null) continue
    const eventIds = [...from.items, ...to.items].map(item => item.id)
    if (surfaced && !eventIds.every(id => surfaced.has(id))) continue
    const transitionScore = from.diversity * from.skipRate + to.topTrackShare + Math.max(0, from.skipRate - to.skipRate)
    outputs.push({
      id: `mode-transition-${outputs.length + 1}`,
      fromDate: from.date,
      toDate: to.date,
      startedAt: from.items[0].occurredAt,
      endedAt: to.items.at(-1)!.occurredAt,
      transitionScore: round(transitionScore),
      transitionType: 'EXPLORATION_TO_CONCENTRATION',
      fromDay: dailyRecord(from),
      toDay: dailyRecord(to),
      eventIds,
      reasonCodes: ['EXPLORATION_TO_CONCENTRATION', 'BEHAVIORAL_MODE_SHIFT'],
      detectorVersion: ANOMALY_DETECTOR_VERSION,
    })
  }
  return outputs.sort((a, b) => b.transitionScore - a.transitionScore)
}

function signal(feature: AnomalyFeature, label: string, value: number, contribution: number): AnomalySignal {
  return { feature, label, value: round(value), baselineMedian: null, standardizedDeviation: null, contribution: round(contribution) }
}

function referenceFor(items: ListeningEvent[]) {
  const counts = new Map<string, { event: ListeningEvent; count: number }>()
  for (const item of items) {
    const key = trackKey(item)
    const prior = counts.get(key)
    counts.set(key, { event: prior?.event ?? item, count: (prior?.count ?? 0) + 1 })
  }
  return [...counts.values()].sort((a, b) => b.count - a.count)[0]
}

function description(codes: CandidateReasonCode[]) {
  const labels: Partial<Record<CandidateReasonCode, string>> = {
    EXTREME_TRACK_REPETITION: 'unusually strong track repetition',
    HIGH_TRACK_CONCENTRATION: 'a high concentration on one track',
    HIGH_MANUAL_SELECTION: 'more explicit track selection than usual',
    BACK_NAVIGATION: 'explicit returns using back navigation',
    HIGH_SKIP_EXPLORATION: 'unusually high skipping',
    UNUSUALLY_LOW_SKIP: 'unusually low skipping',
    LONG_SESSION: 'an unusually long listening session',
    PASSIVE_REPEAT: 'high repetition with little evidence of manual selection',
    HIGH_AGENCY_REPEAT: 'persistent repetition with frequent manual selection',
    MULTI_DAY_RECURRENCE: 'the same track recurring across multiple days',
    EXPLORATION_TO_CONCENTRATION: 'a shift from broad, high-skip listening to concentrated listening',
    RANDOM_CONTROL: 'this period was randomly sampled as a comparison episode',
  }
  const phrases = codes.map(code => labels[code]).filter((value): value is string => Boolean(value)).slice(0, 2)
  return phrases.length ? phrases.join(' and ') : 'a participant-relative behavioral deviation'
}

function stableHash(value: string) {
  let hash = 2166136261
  for (let index = 0; index < value.length; index++) hash = Math.imul(hash ^ value.charCodeAt(index), 16777619)
  return hash >>> 0
}

function episodesFromOutputs(
  profiles: SessionFeatures[],
  baselineCount: number,
  events: ListeningEvent[],
  surfaced: ReadonlySet<string> | undefined,
  outputs: DetectorOutputs,
  maxEpisodes: number,
) {
  const eventById = new Map(events.map(event => [event.id, event]))
  const profileBySession = new Map(profiles.map(profile => [profile.session.id, profile]))
  const candidates: Omit<Episode, 'id'>[] = []
  const usedSessions = new Set<string>()
  const mode: Episode['detectionMode'] = baselineCount >= 5 ? 'PERSONAL_BASELINE' : 'COLD_START'

  for (const [index, output] of outputs.sessionDeviations.entries()) {
    const profile = profileBySession.get(output.sessionId)!
    if (index < 3) usedSessions.add(output.sessionId)
    const reference = referenceFor(profile.items)
    const anomalySignals = [
      signal('REPEAT_INTENSITY', 'Repetition and concentration', output.repeatSignal, output.repeatSignal * 0.35),
      ...(output.activeSignal === null ? [] : [signal('MANUAL_SELECTION', 'Active selection', output.activeSignal, output.activeSignal * 0.30)]),
      ...(output.persistenceSignal === null ? [] : [signal('PERSISTENCE', 'Listening persistence', output.persistenceSignal, output.persistenceSignal * 0.20)]),
      ...(output.skipExtremeScore === null ? [] : [signal('EXPLICIT_SKIP_RATE', 'Skip-rate extremeness', output.skipExtremeScore, output.skipExtremeScore * 0.15)]),
    ].sort((a, b) => b.contribution - a.contribution)
    candidates.push({
      startedAt: output.startedAt,
      endedAt: output.endedAt,
      type: 'HIGH_SURPRISAL',
      title: `${reference.event.artistName} — ${reference.event.trackName}`,
      reason: description(output.reasonCodes),
      referenceTrack: { trackName: reference.event.trackName, artistName: reference.event.artistName, albumName: reference.event.albumName, playCount: reference.count },
      referenceEventId: reference.event.id,
      surprisal: output.deviationScore,
      agency: output.activeSignal ?? 0,
      detectorVersion: output.detectorVersion,
      detectorType: 'SESSION_DEVIATION',
      detectorOutputId: output.id,
      reasonCodes: output.reasonCodes,
      detectorWeights: { REPEAT_INTENSITY: 0.35, MANUAL_SELECTION: 0.30, PERSISTENCE: 0.20, EXPLICIT_SKIP_RATE: 0.15 },
      detectionMode: mode,
      baselineSessionCount: baselineCount,
      anomalySignals,
      eventIds: output.eventIds,
    })
  }

  const maxTrackScore = Math.max(1, ...outputs.persistentTrackIntentionality.map(item => item.agencyPersistenceScore ?? 0))
  const trackPicks = [
    ...outputs.persistentTrackIntentionality.filter(item => item.classification === 'HIGH_AGENCY_REPEAT'),
    ...outputs.persistentTrackIntentionality.filter(item => item.classification === 'PASSIVE_REPEAT').sort((a, b) => b.plays - a.plays),
  ]
  for (const output of trackPicks) {
    const selectedItems = output.eventIds
      .map(id => eventById.get(id))
      .filter((item): item is ListeningEvent => Boolean(item))
      .filter(item => !surfaced || surfaced.has(item.id))
    if (!selectedItems.length) continue
    const days = new Map<string, ListeningEvent[]>()
    for (const item of selectedItems) days.set(dayKey(item.occurredAt), [...(days.get(dayKey(item.occurredAt)) ?? []), item])
    const anchor = [...days.values()].sort((a, b) => b.length - a.length)[0]
    const score = output.agencyPersistenceScore === null ? 0 : output.agencyPersistenceScore / maxTrackScore
    candidates.push({
      startedAt: anchor[0].occurredAt,
      endedAt: anchor.at(-1)!.occurredAt,
      type: 'HIGH_SURPRISAL',
      title: `${output.artistName} — ${output.trackName}`,
      reason: description(output.reasonCodes),
      referenceTrack: { trackName: output.trackName, artistName: output.artistName, albumName: output.albumName, playCount: anchor.length },
      referenceEventId: anchor[0].id,
      surprisal: round(score),
      agency: output.manualRate ?? 0,
      detectorVersion: output.detectorVersion,
      detectorType: 'PERSISTENT_TRACK_INTENTIONALITY',
      detectorOutputId: output.id,
      reasonCodes: output.reasonCodes,
      detectorWeights: { TRACK_PLAY_COUNT: 1 },
      detectionMode: mode,
      baselineSessionCount: baselineCount,
      anomalySignals: [signal('TRACK_PLAY_COUNT', output.classification === 'PASSIVE_REPEAT' ? 'Passive repeat control' : 'Persistent track intentionality', output.plays, score)],
      eventIds: anchor.map(item => item.id),
    })
  }

  const maxTransitionScore = Math.max(1, ...outputs.modeTransitions.map(item => item.transitionScore))
  for (const output of outputs.modeTransitions) {
    const items = output.eventIds.map(id => eventById.get(id)).filter((item): item is ListeningEvent => Boolean(item))
    const reference = referenceFor(items.filter(item => dayKey(item.occurredAt) === output.toDate))
    const score = output.transitionScore / maxTransitionScore
    candidates.push({
      startedAt: output.startedAt,
      endedAt: output.endedAt,
      type: 'HIGH_SURPRISAL',
      title: `${reference.event.artistName} — ${reference.event.trackName}`,
      reason: description(output.reasonCodes),
      referenceTrack: { trackName: reference.event.trackName, artistName: reference.event.artistName, albumName: reference.event.albumName, playCount: reference.count },
      referenceEventId: reference.event.id,
      surprisal: round(score),
      agency: Number(output.toDay.manual_rate ?? 0),
      detectorVersion: output.detectorVersion,
      detectorType: 'MODE_TRANSITION',
      detectorOutputId: output.id,
      reasonCodes: output.reasonCodes,
      detectorWeights: { MODE_TRANSITION: 1 },
      detectionMode: mode,
      baselineSessionCount: baselineCount,
      anomalySignals: [signal('MODE_TRANSITION', 'Exploration-to-concentration transition', output.transitionScore, score)],
      eventIds: output.eventIds,
    })
  }

  const controls = profiles
    .filter(profile => (!surfaced || profile.session.eventIds.every(id => surfaced.has(id))) && !usedSessions.has(profile.session.id) && profile.events >= MIN_SESSION_EVENTS)
    .sort((a, b) => stableHash(a.session.startedAt) - stableHash(b.session.startedAt))
  for (const profile of controls) {
    const reference = referenceFor(profile.items)
    candidates.push({
      startedAt: profile.session.startedAt,
      endedAt: profile.session.endedAt,
      type: 'RANDOM_CONTROL',
      title: `${reference.event.artistName} — ${reference.event.trackName}`,
      reason: description(['RANDOM_CONTROL']),
      referenceTrack: { trackName: reference.event.trackName, artistName: reference.event.artistName, albumName: reference.event.albumName, playCount: reference.count },
      referenceEventId: reference.event.id,
      surprisal: 0,
      agency: profile.manualStartRate ?? 0,
      detectorVersion: ANOMALY_DETECTOR_VERSION,
      detectorType: 'RANDOM_CONTROL',
      detectorOutputId: null,
      reasonCodes: ['RANDOM_CONTROL'],
      detectorWeights: {},
      detectionMode: mode,
      baselineSessionCount: baselineCount,
      anomalySignals: [],
      eventIds: profile.session.eventIds,
    })
  }
  const pool = candidates.map((episode, index): Episode => ({ ...episode, id: `E-${String(index + 1).padStart(4, '0')}` }))
  const quotas: Record<string, number> = { SESSION_DEVIATION: 3, HIGH_AGENCY_REPEAT: 2, PASSIVE_REPEAT: 1, MODE_TRANSITION: 2, RANDOM_CONTROL: 2 }
  const counts: Record<string, number> = {}
  const picked: Episode[] = []
  const selectionAudit = pool.map(episode => {
    const group = episode.detectorType === 'PERSISTENT_TRACK_INTENTIONALITY'
      ? episode.reasonCodes.includes('PASSIVE_REPEAT') ? 'PASSIVE_REPEAT' : 'HIGH_AGENCY_REPEAT'
      : episode.detectorType
    const rank = (counts[group] ?? 0) + 1
    counts[group] = rank
    const selected = rank <= quotas[group] && picked.length < maxEpisodes
    if (selected) picked.push(episode)
    return { episodeId: episode.id, group, rank, selected, selectionProbability: selected ? 1 : 0,
      reason: selected ? 'WITHIN_FAMILY_QUOTA' : rank > quotas[group] ? 'FAMILY_QUOTA_EXCEEDED' : 'PROMPT_BUDGET_EXHAUSTED' }
  })
  return { episodes: picked, candidates: pool, selectionAudit }
}

export function analyzeEvents(
  input: ListeningEvent[],
  surfacedEventIds?: ReadonlySet<string>,
  options: AnalysisOptions = {},
): { sessions: Session[]; episodes: Episode[]; detectorOutputs: DetectorOutputs; candidates: Episode[]; selectionAudit: { episodeId: string; group: string; rank: number; selected: boolean; selectionProbability: number; reason: string }[] } {
  const events = input.map(event => ({ ...event })).sort((a, b) => Date.parse(a.occurredAt) - Date.parse(b.occurredAt))
  const frozenPartition = options.baselineEventIds && surfacedEventIds
    ? [...surfacedEventIds].every(id => !options.baselineEventIds!.has(id))
    : false
  const baselineSessions = frozenPartition
    ? sessionize(events.filter(event => options.baselineEventIds!.has(event.id)), 'baseline-session')
    : []
  const surfacedSessions = frozenPartition
    ? sessionize(events.filter(event => surfacedEventIds!.has(event.id)))
    : sessionize(events)
  const sessions = [...baselineSessions, ...surfacedSessions]
  const eventById = new Map(events.map(event => [event.id, event]))
  const profiles = sessions.map(session => sessionFeatures(session, session.eventIds.map(id => eventById.get(id)!)))
  const referenceProfiles = frozenPartition
    ? profiles.filter(profile => profile.session.id.startsWith('baseline-session-'))
    : options.baselineEventIds
      ? profiles.filter(profile => profile.session.eventIds.every(id => options.baselineEventIds!.has(id)))
    : profiles
  const detectorOutputs: DetectorOutputs = {
    sessionDeviations: computeSessionDeviations(profiles, referenceProfiles, surfacedEventIds),
    persistentTrackIntentionality: computePersistentTracks(events, options.baselineEventIds, surfacedEventIds),
    modeTransitions: computeModeTransitions(events, surfacedEventIds),
  }
  const sampling = episodesFromOutputs(profiles, referenceProfiles.length, events, surfacedEventIds, detectorOutputs, options.maxEpisodes ?? MAX_EPISODES)
  const selectedSessions = surfacedEventIds
    ? sessions.filter(session => session.eventIds.every(id => surfacedEventIds.has(id)))
    : sessions
  return { sessions: selectedSessions, ...sampling, detectorOutputs }
}
