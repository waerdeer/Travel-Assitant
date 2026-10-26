import { useEffect, useId, useState } from "react";
import type { BrowseContext } from "../types";
import PlaceBrowser from "./PlaceBrowser";

export default function InlinePlaceBrowser({
  threadId,
  version,
  context,
  busy,
}: {
  threadId: string;
  version?: string;
  context: BrowseContext;
  busy: boolean;
}) {
  const [open, setOpen] = useState(false);
  const panelId = useId();
  useEffect(() => {
    setOpen(false);
  }, [busy, threadId, version]);
  const label = context.category === "hotel" ? "酒店" : "特色美食";
  return (
    <>
      <button
        type="button"
        className="browse-trigger"
        disabled={busy || !version}
        aria-expanded={open && !busy}
        aria-controls={panelId}
        onClick={() => setOpen((value) => !value)}
      >
        {open && !busy ? "收起" : "浏览"}
        {label}
      </button>
      {open && version && !busy && (
        <PlaceBrowser
          id={panelId}
          threadId={threadId}
          version={version}
          context={context}
          onClose={() => setOpen(false)}
        />
      )}
    </>
  );
}
