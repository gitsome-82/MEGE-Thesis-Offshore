% =========================================================================
%  Alpha Ventus — Wind Speed Visualisation
%  ERA5 actual (100 m) vs ECMWF IFS historical forecast (120 m)
%
%  Data files (same folder as this script):
%    alpha_ventus_wind_actual.csv      → wind_speed_100m_ms
%    alpha_ventus_wind_forecast_hx.csv → wind_speed_120m_ms
%
%  Usage: Run this script in MATLAB. Edit the USER SETTINGS section below
%         to change the date range or switch between preset views.
% =========================================================================

clear; clc; close all;

% ── USER SETTINGS ─────────────────────────────────────────────────────────

% Choose a preset OR set PRESET = 'custom' and fill in DATE_START/DATE_END
%   'full'     → all available data (2022–2026)
%   'year'     → single calendar year  (set YEAR below)
%   'january'  → January of YEAR
%   'summer'   → June–August of YEAR
%   'custom'   → manually set DATE_START and DATE_END

PRESET     = 'january';   % <── change this
YEAR       = 2023;        % used by 'year', 'january', 'summer' presets

DATE_START = datetime(2023, 3, 1);   % used only when PRESET = 'custom'
DATE_END   = datetime(2023, 3, 31);

% Rolling-mean smoothing window (hours). Set to 1 for raw hourly data.
SMOOTH_H   = 24;   % 24 = daily rolling mean, 1 = raw

% ─────────────────────────────────────────────────────────────────────────

% ── Resolve preset date range ─────────────────────────────────────────────
switch lower(PRESET)
    case 'full'
        DATE_START = datetime(2022, 1, 1);
        DATE_END   = datetime(2026, 4, 29);
    case 'year'
        DATE_START = datetime(YEAR, 1,  1);
        DATE_END   = datetime(YEAR, 12, 31, 23, 0, 0);
    case 'january'
        DATE_START = datetime(YEAR, 1,  1);
        DATE_END   = datetime(YEAR, 1, 31, 23, 0, 0);
    case 'summer'
        DATE_START = datetime(YEAR, 6,  1);
        DATE_END   = datetime(YEAR, 8, 31, 23, 0, 0);
    case 'custom'
        % already set above
    otherwise
        error("Unknown PRESET '%s'. Use: full | year | january | summer | custom", PRESET);
end

% ── Load CSVs ─────────────────────────────────────────────────────────────
script_dir = fileparts(mfilename('fullpath'));

actual_file   = fullfile(script_dir, 'alpha_ventus_wind_actual.csv');
forecast_file = fullfile(script_dir, 'alpha_ventus_wind_forecast_hx.csv');

fprintf('Loading actual data …\n');
T_act = readtable(actual_file, 'TextType', 'string');
T_act.datetime = datetime(T_act.datetime, ...
    'InputFormat', 'yyyy-MM-dd HH:mm:ssZ', 'TimeZone', 'UTC');
T_act.Properties.VariableNames{'wind_speed_100m_ms'} = 'actual_ms';

fprintf('Loading forecast data …\n');
T_fct = readtable(forecast_file, 'TextType', 'string');
T_fct.datetime = datetime(T_fct.datetime, ...
    'InputFormat', 'yyyy-MM-dd HH:mm:ssZ', 'TimeZone', 'UTC');
T_fct.Properties.VariableNames{'wind_speed_120m_ms'} = 'forecast_ms';

% ── Merge & filter ────────────────────────────────────────────────────────
T = innerjoin(T_act, T_fct, 'Keys', 'datetime');

mask = T.datetime >= DATE_START & T.datetime <= DATE_END;
T    = T(mask, :);

if isempty(T)
    error('No data in the selected date range (%s → %s)', ...
        datestr(DATE_START), datestr(DATE_END));
end

fprintf('Rows in range: %d  (%s → %s)\n', height(T), ...
    datestr(T.datetime(1)), datestr(T.datetime(end)));

% ── Optional smoothing ────────────────────────────────────────────────────
if SMOOTH_H > 1
    actual_plot   = movmean(T.actual_ms,   SMOOTH_H, 'omitnan');
    forecast_plot = movmean(T.forecast_ms, SMOOTH_H, 'omitnan');
    smooth_label  = sprintf(' (%d-hr mean)', SMOOTH_H);
else
    actual_plot   = T.actual_ms;
    forecast_plot = T.forecast_ms;
    smooth_label  = ' (hourly)';
end

% ── Plot ─────────────────────────────────────────────────────────────────
fig = figure('Name', sprintf('Alpha Ventus Wind — %s', upper(PRESET)), ...
             'Color', 'white', 'Position', [100 100 1100 420]);

plot(T.datetime, actual_plot,   'LineWidth', 1.2, 'Color', [0.17 0.45 0.70]);
hold on;
plot(T.datetime, forecast_plot, 'LineWidth', 1.0, 'Color', [0.93 0.40 0.15], ...
     'LineStyle', '--');

yline(mean(T.actual_ms,   'omitnan'), ':', 'Color', [0.17 0.45 0.70], ...
      'LineWidth', 0.8, 'Alpha', 0.6, 'Label', sprintf('Actual mean %.1f m/s', ...
      mean(T.actual_ms, 'omitnan')), 'LabelHorizontalAlignment', 'left');
yline(mean(T.forecast_ms, 'omitnan'), ':', 'Color', [0.93 0.40 0.15], ...
      'LineWidth', 0.8, 'Alpha', 0.6, 'Label', sprintf('Forecast mean %.1f m/s', ...
      mean(T.forecast_ms, 'omitnan')), 'LabelHorizontalAlignment', 'right');

legend({'ERA5 actual (100 m)', 'ECMWF IFS forecast (120 m)'}, ...
       'Location', 'northeast', 'Box', 'off');

xlabel('Date (UTC)');
ylabel('Wind Speed (m/s)');
title(sprintf('Alpha Ventus — Wind Speed%s   |   %s → %s', ...
    smooth_label, datestr(DATE_START, 'dd mmm yyyy'), datestr(DATE_END, 'dd mmm yyyy')));
grid on;  box off;
xlim([T.datetime(1), T.datetime(end)]);
ylim([0, max([actual_plot; forecast_plot]) * 1.1]);

% ── Summary stats in command window ──────────────────────────────────────
fprintf('\n--- Summary stats for selected period ---\n');
fprintf('                    Actual (100m)   Forecast (120m)\n');
fprintf('Mean  [m/s]       :   %6.2f           %6.2f\n', ...
    mean(T.actual_ms,'omitnan'), mean(T.forecast_ms,'omitnan'));
fprintf('Max   [m/s]       :   %6.2f           %6.2f\n', ...
    max(T.actual_ms), max(T.forecast_ms));
fprintf('Std   [m/s]       :   %6.2f           %6.2f\n', ...
    std(T.actual_ms,'omitnan'), std(T.forecast_ms,'omitnan'));
fprintf('RMSE  actual vs forecast: %.3f m/s\n', ...
    sqrt(mean((T.actual_ms - T.forecast_ms).^2, 'omitnan')));
fprintf('Bias  (fcst - act)      : %+.3f m/s\n', ...
    mean(T.forecast_ms - T.actual_ms, 'omitnan'));
