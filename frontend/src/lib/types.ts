export interface AccountUser {
  id: string; email: string; display_name: string; organization_id: string;
  organization_name: string; locale: string; currency: string; email_verified: boolean; is_platform_admin: boolean;
}
export interface AuthResponse { token: string; user: AccountUser; }
export interface ParticipantListSummary { id: string; name: string; participant_count: number; }
export type CommunicationChannel = "email"|"whatsapp"|"sms"|"telegram";
export type CollectionChannel = "auto"|CommunicationChannel;
export type ChannelAvailability = "unknown"|"available"|"unavailable";
export interface ParticipantChannel { channel: CommunicationChannel; enabled: boolean; availability: ChannelAvailability; learned: boolean; }
export interface Participant { id: string; name: string; email?: string | null; phone?: string | null; locale?: string | null; channel_addresses: Record<string,string>; channels?: ParticipantChannel[]; }
export interface ParticipantListDetail extends ParticipantListSummary { participants: Participant[]; }
export interface ReminderRule { type: "after_send"|"before_due"|"on_due"|"after_due"; days: number; }
export interface CollectionSummary {
  id: string; name: string; participant_list_id: string; amount: string | number; currency: string;
  send_at?: string | null; due_at?: string | null; status: string; participant_count: number;
  paid_count: number; paid_amount: string | number; communication_channel: CollectionChannel; communication_mode: string;
  channel_order: CommunicationChannel[];
  message_template_id?: string | null; reminder_rules: ReminderRule[];
  include_payment_link: boolean; include_payment_qr: boolean;
}
export interface CollectionParticipant {
  id: string; participant_id: string; name: string; email?: string | null; phone?: string | null;
  payment_reference: string; payment_url: string; payment_qr_url?: string | null; status: string;
  paid_at?: string | null; payment_method?: string | null; initial_sent_at?: string | null;
  last_reminder_at?: string | null; reminder_count: number; delivery_status?: string | null;
  delivery_channel?: CommunicationChannel | null; communication_count: number;
}
export interface CollectionDetail extends CollectionSummary { participants: CollectionParticipant[]; }
export interface CollectionMessageTranslations { translations:Record<string,string>; required_languages:string[]; translation_configured:boolean; has_override:boolean; }
export interface ParticipantOpenBalance { participant_id:string; name:string; email?:string|null; phone?:string|null; open_amount:string|number; currency:string; collection_count:number; }
export interface ImportDraft { name: string; email?: string | null; phone?: string | null; selected?: boolean; }
export interface ImportPreview { source_type: string; participants: ImportDraft[]; warnings: string[]; }
export interface ImportResult { imported_count: number; updated_count: number; skipped_count: number; }
export interface PaymentSettingsUpdate { account_name: string; iban: string; bic?: string | null; include_payment_link: boolean; include_payment_qr: boolean; }
export interface PaymentSettings { account_name: string | null; iban: string | null; bic: string | null; configured: boolean; include_payment_link: boolean; include_payment_qr: boolean; }
export interface PublicPayment { collection_name: string; participant_name: string; amount: string | number; currency: string; status: string; paid_at?: string | null; account_name?: string | null; iban?: string | null; bic?: string | null; payment_reference: string; epc_qr_data?: string | null; online_payment_available: boolean; online_payment_provider?: string | null; }
export interface OnlineCheckout { checkout_url: string; provider?: string; }
export interface MessageTemplate { id: string; name: string; translations: Record<string,string>; is_default: boolean; }
export interface TemplateTranslationStatus { configured: boolean; provider: string; supported_languages: string[]; }
export interface BankImportSummary { id: string; filename: string; format: string; created_at: string; transaction_count: number; auto_matched_count: number; review_count: number; unmatched_count: number; duplicate_count: number; transactions?: BankTransaction[]; }
export interface BankMatchSuggestion { collection_participant_id: string; collection_name: string; participant_name: string; amount: string|number; currency: string; payment_reference: string; }
export interface BankTransaction { id: string; booked_at: string; amount: string|number; currency: string; counterparty_name?: string|null; reference?: string|null; status: string; match_confidence?: string|number|null; match_reason?: string|null; candidate_collection_participant_id?: string|null; candidate_collection_name?: string|null; candidate_participant_name?: string|null; suggestions: BankMatchSuggestion[]; }
export interface IntegrationTestResult { ok: boolean; status: string; tested_at: string; error?: string|null; details?: Record<string,unknown>; }
export interface BankSyncConnection { id: string; provider: string; status: string; account_label?: string|null; connected_at?: string|null; last_sync_at?: string|null; last_tested_at?: string|null; last_error?: string|null; }
export interface BankSyncAccount { id: string; external_id: string; name?: string|null; iban?: string|null; currency?: string|null; enabled: boolean; last_sync_at?: string|null; }
export interface BankSyncRunResult { imported: number; auto_matched: number; needs_review: number; duplicates: number; synced_at: string; }
export interface OnlinePaymentConnection { id: string; provider: string; status: string; enabled: boolean; account_label?: string|null; profile_id?: string|null; connected_at?: string|null; last_tested_at?: string|null; last_error?: string|null; }
export interface OnlinePaymentProfile { id: string; name: string; status?: string; }
export interface CommunicationConnection { id: string; provider: string; auth_type: string; status: string; account_label?: string|null; account_key?: string|null; base_url?: string|null; connected_at?: string|null; last_error?: string|null; last_tested_at?: string|null; }
export interface ChannelSetting { channel: CommunicationChannel; mode: "internal"|"external"|"disabled"; provider?: string|null; connection_id?: string|null; sender?: string|null; fields?: Record<string,unknown>; configured: boolean; webhook_url?: string|null; supports_internal?: boolean; status: string; last_tested_at?: string|null; last_error?: string|null; }
export interface CommunicationPreferences { channel_order: CommunicationChannel[]; }
export interface CommunicationItem { id: string; kind: string; channel: string; delivery_mode: string; direction: string; sender?: string|null; recipient?: string|null; subject?: string|null; body?: string|null; status: string; provider?: string|null; created_at: string; sent_at?: string|null; received_at?: string|null; error?: string|null; }
export interface ExternalDraft { message_id: string; channel: CommunicationChannel; launch_uri: string; recipient?: string|null; subject?: string|null; body?: string|null; recipient_selection_required?: boolean; payment_qr_url?: string|null; payment_qr_filename?: string|null; }
export interface DispatchExternalItem { collection_participant_id:string; participant_id:string; name:string; channel:CommunicationChannel; }
export interface DispatchResult { queued_internal:number; external:DispatchExternalItem[]; unreachable:string[]; }
export interface ApiSettings { enabled: boolean; available_scopes: string[]; }
export interface ApiCredential { id: string; name: string; token_prefix: string; scopes: string[]; created_at: string; last_used_at?: string|null; expires_at?: string|null; revoked_at?: string|null; }
export interface ApiCredentialCreated extends ApiCredential { token: string; }
export interface BillingEntitlement { plan:"free"|"pro"; active:boolean; provider:string|null; status:string|null; product_id:string|null; expires_at:string|null; auto_renew:boolean|null; }
export interface BillingPurchaseContext { provider:"apple"|"google"|"mollie"; product_id:string; account_token:string; purchase_allowed:boolean; existing_provider:string|null; existing_status:string|null; reason:string|null; }
export interface GooglePlayBillingConfig { available:boolean; package_name:string; product_id:string; base_plan_id:string; }
export type BillingCustomerType = "consumer"|"business";
export interface BillingProfileWrite { customer_type:BillingCustomerType; given_name:string|null; family_name:string|null; organization_name:string|null; billing_email:string; street_and_number:string; postal_code:string; city:string; region:string|null; country:string; vat_number:string|null; organization_number:string|null; }
export interface BillingProfile extends BillingProfileWrite { vat_validation_status:string; vat_validated_at:string|null; }
export interface BillingInvoice { id:string; provider:string; product_id:string; tariff_version:string; period_start:string; period_end:string; gross_amount:string; currency:string; vat_rate:string; vat_scheme:string; tax_treatment:string; invoice_number:string|null; status:string; payment_url:string|null; paid_at:string|null; }
export interface MollieBillingConfig { available:boolean; product_id:string; amount:string; currency:string; interval:string; environment:"test"|"live"; }
export interface MollieBillingCheckout { checkout_url:string; payment_id:string; resumed:boolean; }
export interface PlatformAdminSummary { customers:number; free_customers:number; pro_customers:number; active_users:number; }
export interface PlatformCustomer { organization_id:string; organization_name:string; created_at:string; locale:string; currency:string; api_enabled:boolean; plan:"free"|"pro"; billing_provider?:string|null; subscription_status?:string|null; subscription_expires_at?:string|null; user_count:number; active_user_count:number; primary_email?:string|null; last_login_at?:string|null; participant_lists:number; participants:number; collections:number; }
export interface PlatformCustomerUser { id:string; email:string; display_name:string; is_active:boolean; email_verified:boolean; created_at:string; last_login_at?:string|null; }
export interface PlatformSubscription { id:string; provider:string; product_id:string; status:string; external_reference?:string|null; purchased_at?:string|null; expires_at?:string|null; cancelled_at?:string|null; auto_renew?:boolean|null; environment?:string|null; last_verified_at?:string|null; created_at:string; updated_at:string; }
