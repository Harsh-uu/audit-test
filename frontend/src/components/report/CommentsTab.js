import React from "react";
import { Send } from "lucide-react";

export function CommentsTab({ meeting, canAddComment, newComment, setNewComment, addComment }) {
  return (
    <div data-testid="comments-view">
      <div className="space-y-3 mb-6">
        {meeting.comments?.length === 0 && (
          <p className="text-sm text-gray-400 text-center py-6">No comments yet</p>
        )}
        {meeting.comments?.map(c => (
          <div key={c.id} className="bg-white border border-gray-200 rounded-lg p-4 shadow-sm">
            <div className="flex items-center justify-between mb-2">
              <span className="text-sm font-medium text-gray-900">{c.user_name}</span>
              <span className="text-xs text-gray-400">{new Date(c.created_at).toLocaleString("en-GB")}</span>
            </div>
            <p className="text-sm text-gray-700">{c.text}</p>
          </div>
        ))}
      </div>
      {canAddComment && (
        <div className="bg-white border border-gray-200 rounded-lg p-4 shadow-sm">
          <textarea
            value={newComment}
            onChange={e => setNewComment(e.target.value)}
            placeholder="Add a comment (read-only viewers only — cannot alter the approved record)..."
            rows={3}
            className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-[#1E3A8A] resize-none"
            data-testid="comment-input"
          />
          <div className="flex justify-end mt-2">
            <button
              onClick={addComment}
              disabled={!newComment.trim()}
              className="flex items-center gap-2 bg-[#1E3A8A] text-white px-4 py-1.5 rounded-md text-sm font-medium hover:bg-[#1E40AF] disabled:opacity-50 transition-colors"
              data-testid="submit-comment-btn"
            >
              <Send className="w-3.5 h-3.5" />
              Add Comment
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
