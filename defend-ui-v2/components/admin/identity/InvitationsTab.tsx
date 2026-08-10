import type { InvitationSummary } from "@/lib/identityApi";

type InvitationsTabProps = {
  invitations: InvitationSummary[];
  onSelect?: (invitation: InvitationSummary) => void;
};

function displayDate(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

export function InvitationsTab({
  invitations,
  onSelect,
}: InvitationsTabProps) {
  return (
    <div className="identity-table-scroll">
      <table aria-label="Invitations" className="identity-table">
        <thead>
          <tr>
            <th scope="col">Recipient</th>
            <th scope="col">Role</th>
            <th scope="col">Creator</th>
            <th scope="col">Delivery</th>
            <th scope="col">Status</th>
            <th scope="col">Created</th>
            <th scope="col">Expires</th>
          </tr>
        </thead>
        <tbody>
          {invitations.map((invitation) => (
            <tr key={invitation.invitation_id}>
              <td>
                <button
                  type="button"
                  className="identity-row-link"
                  onClick={() => onSelect?.(invitation)}
                >
                  {invitation.email}
                </button>
              </td>
              <td>{invitation.intended_role}</td>
              <td>
                {invitation.creator?.display_name ??
                  invitation.creator?.email ??
                  "â€”"}
              </td>
              <td>
                {invitation.delivery_status}
                {invitation.delivery_error ? `: ${invitation.delivery_error}` : ""}
              </td>
              <td>{invitation.status}</td>
              <td>{displayDate(invitation.created_at)}</td>
              <td>{displayDate(invitation.expires_at)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
