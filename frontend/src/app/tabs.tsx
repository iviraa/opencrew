// weather and news tabs live in ./weather; this keeps the shell's imports stable
export { Split, type Scenario } from "./weather/shared";
export { default as WeatherTab } from "./weather/WeatherTab";
export { default as NewsTab } from "./weather/NewsTab";
