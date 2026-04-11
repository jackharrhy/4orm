import { initCsrfFormInterceptor, initHtmxErrorHandler } from "./lib/csrf";
import { initTimeConversion } from "./lib/time";
import { initPushSubscription } from "./lib/push";

// These import and self-register on window:
import "./lib/media";
import "./lib/forum";

// Initialize
initCsrfFormInterceptor();
initHtmxErrorHandler();
initTimeConversion();
initPushSubscription();
