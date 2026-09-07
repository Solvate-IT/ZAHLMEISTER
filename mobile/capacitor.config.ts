import type {CapacitorConfig} from "@capacitor/cli";

const config: CapacitorConfig = {
  appId: "at.solvate.zahlmeister",
  appName: "Zahlmeister",
  webDir: "../frontend/out",
  server: {
    androidScheme: "https",
  },
  plugins: {
    Preferences: {
      group: "Zahlmeister",
    },
  },
};

export default config;
