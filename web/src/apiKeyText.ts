import type { ApiKeyInfo, ApiKeyScope } from './types';

// How the API keys panel words a key (kept apart from the component so it is plain functions).

export const SCOPES: readonly ApiKeyScope[] = ['upload', 'hollow', 'full'];

/** What a key may do, as shown when choosing one. */
export function accessChoice(scope: ApiKeyScope): string {
	if (scope === 'upload') return 'Holecraft: upload models only';
	if (scope === 'hollow') return 'Holecraft: upload models and hollow them';
	return 'Full access: every API';
}

/** What a key may do, as shown in the list. */
function accessSummary(scope: ApiKeyScope): string {
	if (scope === 'upload') return 'Uploads models only';
	if (scope === 'hollow') return 'Uploads and hollows models';
	return 'Full access';
}

/** What a key made for a scope can and cannot do, said once it has been made. */
export function accessNote(scope: ApiKeyScope): string {
	if (scope === 'upload') return 'Access: uploads models only. It cannot read, slice or delete anything.';
	if (scope === 'hollow') return 'Access: uploads models and hollows them. It cannot read, slice or delete anything.';
	return 'Access: every API except making keys. Keep it as private as a password.';
}

const sameDay = (a: Date, b: Date) => a.toDateString() === b.toDateString();
const shortDate = (d: Date) => d.toLocaleDateString(undefined, { day: 'numeric', month: 'short' });

/** "made 14 Oct" */
function madeText(key: ApiKeyInfo): string {
	return `made ${shortDate(new Date(key.created_at))}`;
}

/** "last used today", "last used 2 Oct" or "never used" */
function lastUsedText(key: ApiKeyInfo, now: Date = new Date()): string {
	if (!key.last_used_at) return 'never used';
	const used = new Date(key.last_used_at);
	return sameDay(used, now) ? 'last used today' : `last used ${shortDate(used)}`;
}

/** The whole line under a key's name. */
export function keyDetail(key: ApiKeyInfo, now: Date = new Date()): string {
	return [accessSummary(key.scope), madeText(key), lastUsedText(key, now)].join(' · ');
}
