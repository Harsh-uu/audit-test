export const HOME = {
  emergentLink: "home-emergent-link",
};

export const AUTH = {
  loginEmail: "login-email-input",
  loginPassword: "login-password-input",
  loginSubmit: "login-submit-btn",
  loginError: "login-error",
  toggleRegister: "toggle-register-btn",
  toggleLogin: "toggle-login-btn",
  logoutBtn: "logout-btn",
};

export const DASHBOARD = {
  newMeetingBtn: "new-meeting-btn",
  meetingsList: "meetings-list",
  meetingItem: (id) => `meeting-item-${id}`,
  searchInput: "search-input",
  statusFilter: "status-filter",
  emptyMeetings: "empty-meetings",
};

export const NEW_MEETING = {
  titleInput: "meeting-title-input",
  dateInput: "meeting-date-input",
  locationInput: "meeting-location-input",
  typeSelect: "meeting-type-select",
  step1NextBtn: "step1-next-btn",
  managerSelect: "manager-select",
  createMeetingBtn: "create-meeting-btn",
};

export const RECORDING = {
  notice: "recording-notice",
  acknowledgeBtn: "acknowledge-notice-btn",
  startBtn: "start-recording-btn",
  pauseBtn: "pause-recording-btn",
  resumeBtn: "resume-recording-btn",
  stopBtn: "stop-recording-btn",
  timer: "recording-timer",
  timeline: "event-timeline",
  uploadingState: "uploading-state",
  processingState: "processing-state",
};

export const REPORT = {
  processingIndicator: "processing-indicator",
  summaryText: "summary-text",
  editSummaryBtn: "edit-summary-btn",
  summaryTextarea: "summary-textarea",
  saveSummaryBtn: "save-summary-btn",
  transcriptView: "transcript-view",
  transcriptText: "transcript-text",
  actionsList: "actions-list",
  risksList: "risks-list",
  evidenceCard: (id) => `evidence-card-${id}`,
  markReviewedBtn: "mark-reviewed-btn",
  signOffBtn: "sign-off-btn",
  commentsTab: "comments-tab",
  commentInput: "comment-input",
  submitCommentBtn: "submit-comment-btn",
  audioStatus: "audio-status",
  actionMessage: "action-message",
};

export const ADMIN = {
  addStandardBtn: "add-standard-btn",
  addUserBtn: "add-user-btn",
  standardsTable: "standards-table",
  usersTable: "users-table",
  uploadDocBtn: "upload-doc-btn",
};
