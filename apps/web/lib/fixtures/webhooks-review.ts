import { unattendedMeeting } from "../script";

export const webhooksReview = unattendedMeeting({
  id: "webhooks-security-review-2026-09-07",
  title: "Security review: webhooks v2",
  start: "2026-09-07T11:00:00+08:00",
  platform: "Google Meet",
  host: "sam",
  attendees: ["sam", "weijie", "nadia"],
  lobbyWait: 600,
  context: [
    { kind: "calendar", label: "Invite", detail: "3 guests" },
    { kind: "drive", label: "Webhooks v2 threat model", detail: "Updated Fri 4 Sep" },
    { kind: "slack", label: "#security", detail: "14 messages from the last 7 days" },
  ],
});
