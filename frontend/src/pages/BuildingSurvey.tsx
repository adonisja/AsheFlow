import CollectionData from './superadmin/CollectionData';

/** A company's own building survey (ADR-423).
 *
 *  The same component the platform owner uses, in its company view. It is not
 *  a copy: the endpoints scope themselves by caller, so a company admin's
 *  reads return only their own rows and the link they issue is company-scoped.
 *  Sharing the component means the campaign list, the drill-down, the exports
 *  and the token controls cannot drift between the two audiences.
 *
 *  The route gate (`management`, `admin`) is a convenience so the page is not
 *  offered to someone it would 403 for. The real gate is `_scope_reads` on the
 *  server, which refuses anyone else regardless of how they got here.
 */
export default function BuildingSurvey() {
  return <CollectionData platform={false} />;
}
