import React from "react";
import { FileText } from "lucide-react";
import { anonymiseTranscript } from "@/utils/anonymise";

export function TranscriptTab({ meeting }) {
  return (
    <div data-testid="transcript-view">
      <div className="bg-amber-50 border border-amber-200 rounded-md p-3 mb-4 flex items-center gap-2">
        <FileText className="w-4 h-4 text-amber-600 flex-shrink-0" />
        <p className="text-xs text-amber-700">Transcript is read-only. Use the Evidence tab to edit summaries and evidence wording.</p>
      </div>
      <div className="bg-white border border-gray-200 rounded-lg p-5 shadow-sm">
        <pre className="text-sm text-gray-700 whitespace-pre-wrap font-[inherit] leading-relaxed" data-testid="transcript-text">
          {anonymiseTranscript(meeting.transcript?.text, meeting.attendees || []) || "Transcript not available."}
        </pre>
      </div>
    </div>
  );
}
