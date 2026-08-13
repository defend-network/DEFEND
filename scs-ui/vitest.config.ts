import { defineConfig } from "vitest/config";
export default defineConfig({resolve:{alias:{"@":import.meta.dirname}},test:{environment:"jsdom",globals:true,setupFiles:["./vitest.setup.ts"]}});
