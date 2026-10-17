import type {BudgetStatus} from '@/lib/api-types';
import {budgetView} from '@/lib/attendance';
import styles from './BudgetPanel.module.css';
export function BudgetPanel({status}:{status:BudgetStatus}) {
 const v=budgetView(status);
 const usd=(n:number)=>new Intl.NumberFormat('en-US',{style:'currency',currency:'USD'}).format(n/1e6);
 return <section className={styles.panel} aria-labelledby="budget-title">
  <h2 id="budget-title">Monthly AI budget</h2>
  <p className={styles.period}>{status.month} · {status.timezone}</p>
  {v.warning&&<p role="status" className={styles.warning}>Soft limit reached. Paid work continues within the remaining hard budget.</p>}
  {status.last_denied&&<p role="status" className={styles.warning}>A request could not fit in the remaining budget. Saved notes and free controls remain available.</p>}
  <dl className={styles.amounts}>
   <div><dt>Settled estimate</dt><dd>{v.settled}</dd></div>
   <div><dt>Held reservations</dt><dd>{v.held}</dd></div>
   <div><dt>Available</dt><dd>{v.available}</dd></div>
   <div><dt>Soft / hard limit</dt><dd>{v.soft} / {v.hard}</dd></div>
  </dl>
  <p>Resets {v.reset} ({status.timezone}).</p>
  {status.uncertain_count>0&&<p>{status.uncertain_count} possibly charged request(s) remain held for review.</p>}
  <details><summary>Provider estimates and scope</summary>
   {Object.entries(status.providers).map(([name,cost])=><p key={name}>{name}: {usd(cost.settled_micro_usd)} settled · {usd(cost.held_micro_usd)} held</p>)}
   <p>{status.scope} Rates checked {status.price_version}. This is an application estimate; provider invoices can differ.</p>
  </details>
 </section>;
}
