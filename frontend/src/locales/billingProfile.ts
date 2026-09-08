import {billingProfileMessagesA} from "./billingProfileA";
import {billingProfileMessagesB} from "./billingProfileB";
import type {BillingProfileMessages} from "./billingProfileShared";

export const billingProfileMessages:Record<string,BillingProfileMessages>={
  ...billingProfileMessagesA,
  ...billingProfileMessagesB,
};
