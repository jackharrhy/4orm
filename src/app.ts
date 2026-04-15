import { initHtmxErrorHandler } from "./lib/csrf";
import { initTimeConversion } from "./lib/time";
import { initPushSubscription } from "./lib/push";
import { initChat } from "./lib/chat";

// These import and self-register on window:
import "./lib/media";
import "./lib/forum";

// Initialize
initHtmxErrorHandler();
initTimeConversion();
initPushSubscription();
initChat();
