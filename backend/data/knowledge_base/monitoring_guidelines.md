# Network Monitoring and Data Validation Guidelines

## Data completeness
A 24-hour average is valid only when at least 75 % (18 of 24) of hourly values are available. An 8-hour average requires at least 6 valid hours. Values computed with lower coverage are reported as indicative only and are not used to declare an exceedance.

## Averaging period compatibility
A sensor value must be compared with a standard that uses the same averaging period. A single 1-hour reading must not be compared directly against a 24-hour or annual limit. The system computes the rolling average that matches the standard before declaring an exceedance. Annual standards require at least 75 % of a year of data and are reported as not assessable otherwise.

## Suspicious measurements
Suspicious values (physically impossible readings, PM2.5 greater than PM10, abrupt single-hour jumps that revert, flat-lined signals) are flagged for verification and retained. They are never silently deleted.

## Stale sensors
A station is considered stale when no data has been received for more than 3 expected reporting intervals (3 hours for hourly stations).

## Language for source attribution
Monitoring data alone cannot establish the cause of an event. Reports must use the terms "potential contributing source" or "source requiring investigation" unless the source has been independently confirmed by inspection or laboratory evidence.
