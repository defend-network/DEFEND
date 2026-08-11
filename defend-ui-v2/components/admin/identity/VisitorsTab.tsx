import type { ClientMetadata, VisitorSummary } from "@/lib/identityApi";

type VisitorsTabProps = {
  visitors: VisitorSummary[];
  onSelect?: (visitor: VisitorSummary) => void;
};

function displayDate(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

function clientLabel(client: ClientMetadata): string {
  return [client.browser, client.platform, client.device]
    .filter((value): value is string => typeof value === "string" && value.length > 0)
    .join(" / ") || "â€”";
}

export function VisitorsTab({ visitors, onSelect }: VisitorsTabProps) {
  return (
    <div className="identity-table-scroll">
      <table aria-label="Visitors" className="identity-table">
        <thead>
          <tr>
            <th scope="col">Visitor ID</th>
            <th scope="col">Linked account</th>
            <th scope="col">Client</th>
            <th scope="col">Recent IP</th>
            <th scope="col">First seen</th>
            <th scope="col">Last seen</th>
            <th scope="col">Visits</th>
            <th scope="col">Sessions / activity</th>
          </tr>
        </thead>
        <tbody>
          {visitors.map((visitor) => (
            <tr key={visitor.visitor_id}>
              <td>
                <button
                  type="button"
                  className="identity-row-link"
                  onClick={() => onSelect?.(visitor)}
                >
                  {visitor.visitor_id}
                </button>
              </td>
              <td>
                {visitor.linked_account ? (
                  <>
                    <strong>{visitor.linked_account.display_name}</strong>
                    <span>{visitor.linked_account.email}</span>
                  </>
                ) : (
                  "Anonymous"
                )}
              </td>
              <td>{clientLabel(visitor.client_meta)}</td>
              <td>{visitor.recent_ip ?? "â€”"}</td>
              <td>{displayDate(visitor.first_seen)}</td>
              <td>{displayDate(visitor.last_seen)}</td>
              <td>{visitor.seen_count}</td>
              <td>
                {visitor.session_count} sessions / {visitor.conversation_count} conversations /{" "}
                {visitor.message_count} messages
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
