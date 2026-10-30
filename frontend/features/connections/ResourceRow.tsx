"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/Button";
import { ApiError, messageFor } from "@/lib/api/errors";
import { formatSyncedAt } from "@/lib/format/availability";

import {
  jobFinished,
  keys,
  useJob,
  useLinkHistory,
  useLinkResource,
  useRequestSync,
  type Resource,
} from "./api";
import styles from "./connections.module.css";
import {
  JOB_STATUS,
  RESOURCE_KIND,
  UNLINK_REASON,
  connectError,
  unavailableReason,
} from "./labels";

export type RowNotice = { tone: "success" | "error"; text: string; requestId: string | null };

function when(value: string): string {
  return new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(
    new Date(value),
  );
}

export function ResourceRow({
  orgId,
  connectionId,
  resource,
  canManage,
  connectionActive,
  onNotice,
}: {
  orgId: string;
  connectionId: string;
  resource: Resource;
  canManage: boolean;
  connectionActive: boolean;
  onNotice: (n: RowNotice) => void;
}) {
  const queryClient = useQueryClient();
  const link = useLinkResource(orgId, connectionId);
  const sync = useRequestSync(orgId);
  const [jobId, setJobId] = useState<string | null>(null);
  const job = useJob(orgId, jobId);
  const [showHistory, setShowHistory] = useState(false);
  const history = useLinkHistory(orgId, resource.id, showHistory);
  const name = resource.display_name || resource.external_id;
  const unavailable = unavailableReason(resource.unavailable_reason, resource.provider);

  // When a sync finishes, refresh the list so "Last synced" updates.
  const finished = jobFinished(job.data);
  useEffect(() => {
    if (finished)
      void queryClient.invalidateQueries({ queryKey: keys.resources(orgId, connectionId) });
  }, [finished, queryClient, orgId, connectionId]);

  const fail = (error: unknown) =>
    onNotice({
      tone: "error",
      text: messageFor(error),
      requestId: error instanceof ApiError ? error.requestId : null,
    });

  function toggleLink() {
    const linking = !resource.linked;
    link.mutate(
      { resourceId: resource.id, link: linking },
      {
        onSuccess: () => {
          void queryClient.invalidateQueries({ queryKey: keys.resources(orgId, connectionId) });
          void queryClient.invalidateQueries({ queryKey: keys.links(orgId, resource.id) });
          onNotice({
            tone: "success",
            text: linking ? `${name} is now linked to this organization.` : `${name} was unlinked.`,
            requestId: null,
          });
        },
        onError: fail,
      },
    );
  }

  function requestSync() {
    sync.mutate(resource.id, { onSuccess: (queued) => setJobId(queued.id), onError: fail });
  }

  // A job that can no longer be read (role changed, API unavailable) stops being followed, so
  // the button becomes usable again and the reason is shown.
  const settled = finished || Boolean(job.error);
  const jobText = job.error
    ? `Sync status unavailable — ${messageFor(job.error)}`
    : job.data
      ? `Sync: ${JOB_STATUS[job.data.status] ?? job.data.status}${
          job.data.last_error_code && job.data.status !== "succeeded"
            ? ` — ${connectError(job.data.last_error_code)}`
            : ""
        }`
      : jobId
        ? "Sync: Waiting to start"
        : null;

  return (
    <tr>
      <td>
        <strong>{name}</strong>
        <br />
        <span className={styles.muted}>
          {RESOURCE_KIND[resource.kind] ?? resource.kind} · ID {resource.external_id}
        </span>
        {!resource.accessible ? (
          <>
            <br />
            <span className={`${styles.status} ${styles.warn}`}>No longer accessible</span>
          </>
        ) : null}
        {unavailable ? (
          <>
            <br />
            <span className={`${styles.status} ${styles.warn}`}>Cannot be linked</span>{" "}
            <span className={styles.muted}>{unavailable}</span>
          </>
        ) : null}
      </td>
      <td>
        {[resource.currency, resource.timezone?.replaceAll("_", " ")]
          .filter(Boolean)
          .join(" · ") || <span className={styles.muted}>Not provided</span>}
      </td>
      <td>
        {resource.linked ? (
          <span className={`${styles.status} ${styles.ok}`}>Linked</span>
        ) : (
          <span className={`${styles.status} ${styles.off}`}>Not linked</span>
        )}
      </td>
      <td>
        {formatSyncedAt(resource.last_synced_at)}
        {jobText ? (
          <p role="status" className={styles.muted}>
            {jobText}
          </p>
        ) : null}
      </td>
      <td>
        <div className={styles.actions}>
          {canManage &&
          connectionActive &&
          (resource.linked || (resource.accessible && !unavailable)) ? (
            <Button
              variant={resource.linked ? "secondary" : "primary"}
              busy={link.isPending}
              aria-label={`${resource.linked ? "Unlink" : "Link"} ${name}`}
              onClick={toggleLink}
            >
              {resource.linked ? "Unlink" : "Link"}
            </Button>
          ) : null}
          {canManage && connectionActive && resource.linked ? (
            <Button
              variant="secondary"
              busy={sync.isPending || (jobId !== null && !settled)}
              aria-label={`Sync ${name} now`}
              onClick={requestSync}
            >
              Sync now
            </Button>
          ) : null}
          <Button
            variant="link"
            aria-expanded={showHistory}
            aria-label={`${showHistory ? "Hide" : "Show"} link history for ${name}`}
            onClick={() => setShowHistory((v) => !v)}
          >
            History
          </Button>
        </div>
        {showHistory ? (
          history.data?.length ? (
            <ul className={styles.history}>
              {[...history.data].reverse().map((h) => (
                <li key={h.id}>
                  Linked {when(h.linked_at)}
                  {h.unlinked_at
                    ? ` · unlinked ${when(h.unlinked_at)}${h.unlink_reason ? ` (${UNLINK_REASON[h.unlink_reason] ?? h.unlink_reason})` : ""}`
                    : " · still linked"}
                </li>
              ))}
            </ul>
          ) : history.isPending ? (
            <p role="status" className={styles.muted}>
              Loading history…
            </p>
          ) : history.error ? (
            <p className={styles.muted}>{messageFor(history.error)}</p>
          ) : (
            <p className={styles.muted}>Never linked.</p>
          )
        ) : null}
      </td>
    </tr>
  );
}
