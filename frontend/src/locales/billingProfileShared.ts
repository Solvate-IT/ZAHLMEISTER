export type BillingProfileMessages = Record<string,string>;

const billingProfileKeys = ["billingDetailsTitle","billingDetailsHint","billingDetailsEdit","billingDetailsSave","billingDetailsSaved","billingCustomerType","billingConsumer","billingBusiness","billingFirstName","billingFamilyName","billingLegalName","billingEmail","billingStreet","billingPostalCode","billingCity","billingRegion","billingCountry","billingCountryChoose","billingVatNumber","billingOrganizationNumber","billingVatHint","billingProfileRequired","billingProfileInvalid","billingTaxUnavailable","billingTaxScopeHint","billingInvoicesTitle","billingInvoicesHint","billingNoInvoices","billingInvoiceNumber","billingInvoicePeriod","billingInvoiceAmount","billingInvoiceVat","billingInvoiceStatus","billingInvoicePay","billingInvoicePaid","billingInvoicePending","billingInvoiceIssued","billingInvoiceOverdue","billingInvoiceReversed","billingInvoiceCancelled","billingRequiredFields","billingPriceYear","billingNextRenewal","billingAutoDebitMandate","billingCancelQuestion"] as const;

export function makeBillingProfileMessages(values: readonly string[]): BillingProfileMessages {
  if (values.length !== billingProfileKeys.length) throw new Error("Invalid billing profile translation catalog");
  return Object.fromEntries(billingProfileKeys.map((key,index)=>[key,values[index]])) as BillingProfileMessages;
}
