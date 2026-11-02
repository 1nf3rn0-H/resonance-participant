import { defineConfig } from '@playwright/test'
export default defineConfig({testDir:'tests/browser',workers:1,timeout:120000,retries:0,reporter:[['list'],['html',{outputFolder:'playwright-report',open:'never'}]],use:{headless:true,trace:'retain-on-failure',screenshot:'only-on-failure',launchOptions:{args:['--no-sandbox','--disable-dev-shm-usage']}}})
