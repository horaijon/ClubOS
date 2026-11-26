export interface AuthSession {
 account_id: string|null;
 name: string;
 email: string|null;
 role: string;
 demo: boolean;
 club: {id:string;name:string;college:string;available_funds:number}|null;
}
export interface EventRecord {
  id: string; name: string; type: string; description: string; venue: string; start_date: string; end_date: string;
  target: number; initial_budget: number; sponsorship_target: number; club: string; college: string; is_demo: boolean; goals: string;
}
export interface Metrics {
  planned: number; exposure: number; actual: number; committed: number; received: number; projected_funding: number; balance: number;
  cash_balance: number; shortfall: number; outstanding: number; registered: number; target: number; completed: number;
  total_tasks: number; overdue: number; active_risks: number; pending_approvals: number; readiness: number; actions: number; minutes_saved: number;
}
export interface Task { id: string; title: string; description: string; department: string; owner: string; status: string; priority: string; due_date: string; }
export interface Run {id:string; agent:string; trigger:string; tool?:string; summary:string; mode:string; status:string; created_at:string; workflow_id:string;}
export interface RegistrationForm {
  slug:string; deadline:string; public_url?:string; fields:{key:string;label:string}[];
  is_google_form?:boolean; google_form_id?:string; responder_uri?:string; edit_uri?:string; response_count?:number;
}
export interface SponsorItem {
  id:string; name:string; stage:string; industry?:string; committed?:number; received?:number; contact_email?:string; draft?:string;
}
export interface ApprovalItem {
  id:string; title:string; description?:string; status:string; workflow_id?:string; risk_id?:string; created_at?:string;
  actions?:{type:string; title:string; amount?:number; saving?:number; [k:string]:unknown}[];
}
export interface PosterItem {
  id:string; event_id:string; title:string; kind:'generated'|'reference'|'final';
  prompt:string; theme:string; mime_type:string; is_active:boolean;
  created_by:string; created_at:string; image_url:string;
  design?:Record<string,unknown>;
}
export interface AppealRecord {
  id:string; event_id:string; target_type:string; target_id:string; title:string;
  reason:string; override_request:string; status:'Flagged'|'Under Review'|'Overridden'|'Dismissed';
  resolution_note:string; submitted_by:string; created_at:string; updated_at:string;
}
export interface AuditLogRecord {
  id:string; appeal_id?:string|null; actor:string; from_status:string; to_status:string; note:string; created_at:string;
}
export interface Snapshot {
  disruptions?: {
    id:string;
    title:string;
    kind?:string;
    summary?:string;
    created_at?:string;
    changes:{record:string;field:string;before:string;after:string;audience:string}[];
    actions_taken?:string[];
    notifications?:{recipient_name:string;recipient_email:string;role:string;subject:string;body:string;status:string;channel:string;detail?:string}[];
  }[];
  event_brief?: { prompt: string; details: { tracks?: string[]; team_rules?: string; prizes?: string } } | null;
 registration_form: RegistrationForm|null;
 event: EventRecord; metrics: Metrics; tasks: Task[]; sponsors: SponsorItem[];
 budget:{id:string;category:string;planned:number;actual:number}[]; risks:{id:string;title:string;severity:string;status:string}[];
 approvals:ApprovalItem[]; runs: Run[]; marketing: unknown[];
 participants:{id:string;name?:string;email?:string;checked_in?:number;created_at:string;answers?:Record<string,string>}[]; members:{id:string;name:string;role:string}[];
 registration_history?:{date:string;count:number;cumulative:number}[]; activity:{id:string;title:string;description:string;agent:string;created_at:string}[];
 posters?: PosterItem[];
 appeals?: AppealRecord[];
 decision_audit_logs?: AuditLogRecord[];
}
export interface GoogleStatus {
  connected: boolean;
  email: string | null;
  available: boolean;
}
export type EventOption = Pick<EventRecord,'id'|'name'>;
const currency = new Intl.NumberFormat('en-IN', {style:'currency',currency:'INR',minimumFractionDigits:0,maximumFractionDigits:2});
export const money = (paise=0) => currency.format(paise / 100);
export function dateOf(value:string) { return new Date(/^\d{4}-\d{2}-\d{2}$/.test(value) ? value+'T00:00:00' : value); }
export function shortDate(value:string, long=false) {
 const date = dateOf(value);
 return Number.isNaN(date.getTime()) ? 'Date pending' : date.toLocaleDateString('en-GB',{day:'numeric',month:long?'long':'short',...(long?{year:'numeric'}:{})});
}
export const ratio = (numerator:number, denominator:number) => denominator>0 ? Math.round(numerator*100/denominator) : 0;
export async function api<T>(url:string, options?:RequestInit): Promise<T> {
 const response = await fetch(url,{...options,headers:{...(options?.body?{'Content-Type':'application/json'}:{}),...options?.headers}});
 const body = await response.json().catch(()=>null);
 if(!response.ok) {
   const detail=body?.detail;
   const message=typeof detail==='string'?detail:Array.isArray(detail)?detail.map((issue:{msg:string})=>issue.msg).join('. '):'The workspace could not complete this request.';
   throw new Error(message);
 }
 return body as T;
}
export function saved(key:string) { try {return localStorage.getItem('clubos.v1.'+key)} catch { return null } }
export function save(key:string,value:string) { try {localStorage.setItem('clubos.v1.'+key,value)} catch { /* Browsing without storage still works. */ } }
