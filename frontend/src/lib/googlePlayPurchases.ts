"use client";

import {Capacitor,registerPlugin} from "@capacitor/core";
import type {GooglePlayBillingConfig} from "@/lib/types";

interface GooglePlayProduct {
  identifier:string;
  planIdentifier?:string;
  offerToken?:string;
  offerId?:string|null;
  priceString:string;
  currencyCode:string;
}

interface GooglePlayTransaction {
  productIdentifier:string;
  purchaseToken?:string;
  purchaseState?:string;
}

interface NativePurchasesPlugin {
  isBillingSupported():Promise<{isBillingSupported:boolean}>;
  getProducts(options:{productIdentifiers:string[];productType:"subs"}):Promise<{products:GooglePlayProduct[]}>;
  purchaseProduct(options:{productIdentifier:string;planIdentifier:string;offerToken?:string;productType:"subs";appAccountToken:string;autoAcknowledgePurchases:false}):Promise<GooglePlayTransaction>;
  getPurchases(options:{productType:"subs";appAccountToken:string}):Promise<{purchases:GooglePlayTransaction[]}>;
  manageSubscriptions():Promise<void>;
}

const NativePurchases=registerPlugin<NativePurchasesPlugin>("NativePurchases");

export interface GooglePlayOffer {
  price:string;
  currency:string;
}

export function isGooglePlayBillingRuntime():boolean{
  return typeof window!=="undefined"&&Capacitor.getPlatform()==="android"&&Capacitor.isPluginAvailable("NativePurchases");
}

async function selectedOffer(config:GooglePlayBillingConfig):Promise<GooglePlayProduct>{
  if(!isGooglePlayBillingRuntime())throw new Error("Google Play Billing is not installed in this Android build");
  const support=await NativePurchases.isBillingSupported();
  if(!support.isBillingSupported)throw new Error("Google Play Billing is not supported on this device");
  const {products}=await NativePurchases.getProducts({productIdentifiers:[config.product_id],productType:"subs"});
  const candidates=products.filter(item=>item.identifier===config.base_plan_id&&item.planIdentifier===config.product_id);
  const product=candidates.find(item=>!item.offerId)??candidates[0];
  if(!product)throw new Error("Configured Google Play subscription/base plan was not found");
  return product;
}

export async function getGooglePlayOffer(config:GooglePlayBillingConfig):Promise<GooglePlayOffer>{
  const product=await selectedOffer(config);
  return {price:product.priceString,currency:product.currencyCode};
}

export async function purchaseGooglePlayPro(config:GooglePlayBillingConfig,accountToken:string):Promise<string>{
  const product=await selectedOffer(config);
  const transaction=await NativePurchases.purchaseProduct({
    productIdentifier:config.product_id,
    planIdentifier:config.base_plan_id,
    offerToken:product.offerToken,
    productType:"subs",
    appAccountToken:accountToken,
    autoAcknowledgePurchases:false,
  });
  if(transaction.purchaseState!=="1"||!transaction.purchaseToken)throw new Error("Google Play purchase is not completed yet");
  return transaction.purchaseToken;
}

export async function currentGooglePlayPurchaseTokens(config:GooglePlayBillingConfig,accountToken:string):Promise<string[]>{
  if(!isGooglePlayBillingRuntime())return [];
  const {purchases}=await NativePurchases.getPurchases({productType:"subs",appAccountToken:accountToken});
  return [...new Set(purchases
    .filter(item=>item.productIdentifier===config.product_id&&item.purchaseState==="1"&&Boolean(item.purchaseToken))
    .map(item=>item.purchaseToken as string))];
}

export async function manageGooglePlaySubscriptions():Promise<void>{
  if(!isGooglePlayBillingRuntime())throw new Error("Google Play Billing is not installed in this Android build");
  await NativePurchases.manageSubscriptions();
}
