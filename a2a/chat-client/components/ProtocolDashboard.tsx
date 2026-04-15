/*
 * Copyright 2026 UCP Authors
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *     http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */
import type { ProtocolExchangeEvent } from "../types";

interface ProtocolDashboardProps {
  events: ProtocolExchangeEvent[];
  isOpen: boolean;
  onToggle: () => void;
  onClear: () => void;
}

function prettyJson(value: unknown): string {
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

function formatTime(isoValue: string): string {
  const date = new Date(isoValue);
  return Number.isNaN(date.getTime()) ? isoValue : date.toLocaleTimeString();
}

function getProtocolStages(event: ProtocolExchangeEvent): string[] {
  if (!event.protocolTrace || !Array.isArray(event.protocolTrace)) {
    return [];
  }
  return event.protocolTrace
    .map((entry) => {
      if (!entry || typeof entry !== "object") {
        return null;
      }
      const stage = (entry as Record<string, unknown>).stage;
      return typeof stage === "string" ? stage : null;
    })
    .filter((stage): stage is string => typeof stage === "string");
}

function usesAdkRunner(stages: string[]): boolean {
  return stages.some((stage) => stage.startsWith("a2a.llm_path"));
}

function stageLabel(stage: string): string {
  return stage
    .replace(/^a2a\./, "")
    .replace(/^ucp\./, "ucp/")
    .replaceAll(".", " -> ");
}

function ProtocolDashboard({
  events,
  isOpen,
  onToggle,
  onClear,
}: ProtocolDashboardProps) {
  return (
    <aside
      className={`protocol-dashboard flex flex-col border-slate-200 bg-white/90 backdrop-blur md:border-l ${
        isOpen
          ? "max-h-[48vh] border-t md:max-h-none md:w-[430px]"
          : "max-h-[56px] border-t md:max-h-none md:w-[58px]"
      }`}
    >
      <div className="flex items-center justify-between border-b border-slate-200 px-3 py-2">
        <button
          type="button"
          className="protocol-toggle rounded-md border border-slate-200 px-2 py-1 text-xs font-semibold uppercase tracking-wide text-slate-600"
          onClick={onToggle}
        >
          {isOpen ? "Hide Trace" : "Trace"}
        </button>
        {isOpen && (
          <button
            type="button"
            className="rounded-md border border-slate-200 px-2 py-1 text-xs text-slate-600 hover:bg-slate-100"
            onClick={onClear}
          >
            Clear
          </button>
        )}
      </div>

      {isOpen && (
        <div className="protocol-scroll flex-1 overflow-y-auto p-3">
          <h2 className="mb-2 text-sm font-bold text-slate-800">
            Protocol Dashboard
          </h2>
          {events.length === 0 ? (
            <p className="text-xs text-slate-500">
              Send a message to inspect JSON-RPC requests, token payloads, and
              protocol traces.
            </p>
          ) : (
            <div className="space-y-3">
              {events
                .slice()
                .reverse()
                .map((event) => (
                  <article
                    key={event.id}
                    className="rounded-xl border border-slate-200 bg-slate-50 p-3 shadow-sm"
                  >
                    <div className="mb-2 flex items-center justify-between gap-2">
                      <span
                        className={`rounded-full px-2 py-0.5 text-[11px] font-semibold uppercase ${
                          event.direction === "outbound"
                            ? "bg-sky-100 text-sky-700"
                            : "bg-emerald-100 text-emerald-700"
                        }`}
                      >
                        {event.direction}
                      </span>
                      <span className="text-[11px] text-slate-500">
                        {formatTime(event.timestamp)}
                      </span>
                    </div>

                    <p className="text-sm font-semibold text-slate-800">
                      {event.title}
                    </p>
                    <p className="mt-1 text-[12px] text-slate-600">
                      {event.httpMethod} {event.endpoint}
                      {event.httpStatus !== undefined
                        ? ` • HTTP ${event.httpStatus}`
                        : ""}
                    </p>
                    {(event.contextId || event.taskId) && (
                      <p className="mt-1 text-[11px] text-slate-500">
                        context: {event.contextId || "-"} | task:{" "}
                        {event.taskId || "-"}
                      </p>
                    )}

                    {(() => {
                      const stages = getProtocolStages(event);
                      if (stages.length === 0) {
                        return null;
                      }
                      const adkUsed = usesAdkRunner(stages);
                      return (
                        <div className="mt-2 rounded-lg border border-slate-200 bg-white p-2">
                          <p className="text-[11px] font-semibold uppercase tracking-wide text-slate-600">
                            A2A/UCP Call Flow
                          </p>
                          <p className="mt-1 text-[11px] text-slate-600">
                            ADK Runner Used:{" "}
                            <span
                              className={`font-semibold ${
                                adkUsed ? "text-emerald-700" : "text-amber-700"
                              }`}
                            >
                              {adkUsed ? "Yes" : "No (Fast Path)"}
                            </span>
                          </p>
                          <ol className="mt-2 space-y-1">
                            {stages.map((stage, index) => (
                              <li
                                key={`${event.id}-${stage}-${index}`}
                                className="rounded-md bg-slate-100 px-2 py-1 text-[11px] text-slate-700"
                              >
                                {index + 1}. {stageLabel(stage)}
                              </li>
                            ))}
                          </ol>
                        </div>
                      );
                    })()}

                    {event.tokens && event.tokens.length > 0 && (
                      <div className="mt-2">
                        <p className="text-[11px] font-semibold uppercase tracking-wide text-slate-600">
                          Tokens
                        </p>
                        <div className="mt-1 space-y-1">
                          {event.tokens.map((token) => (
                            <code
                              key={`${event.id}-${token}`}
                              className="block rounded bg-slate-200/70 px-2 py-1 text-[11px] text-slate-700"
                            >
                              {token}
                            </code>
                          ))}
                        </div>
                      </div>
                    )}

                    <details className="mt-2">
                      <summary className="cursor-pointer text-[11px] font-semibold uppercase tracking-wide text-slate-600">
                        Headers
                      </summary>
                      <pre className="protocol-json mt-2">{prettyJson(event.headers)}</pre>
                    </details>

                    <details className="mt-2" open>
                      <summary className="cursor-pointer text-[11px] font-semibold uppercase tracking-wide text-slate-600">
                        JSON-RPC
                      </summary>
                      <pre className="protocol-json mt-2">
                        {prettyJson(event.jsonrpcPayload)}
                      </pre>
                    </details>

                    {event.protocolTrace && (
                      <details className="mt-2">
                        <summary className="cursor-pointer text-[11px] font-semibold uppercase tracking-wide text-slate-600">
                          A2A/UCP Internal Trace
                        </summary>
                        <pre className="protocol-json mt-2">
                          {prettyJson(event.protocolTrace)}
                        </pre>
                      </details>
                    )}
                  </article>
                ))}
            </div>
          )}
        </div>
      )}
    </aside>
  );
}

export default ProtocolDashboard;
