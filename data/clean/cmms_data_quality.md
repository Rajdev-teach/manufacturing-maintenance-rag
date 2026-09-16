# CMMS Data Quality and Failure Coding

## Asset records
Each asset needs a unique ID, standardized name, location, manufacturer, model, serial number, criticality, parent asset, and commissioning date. Duplicate IDs and free-text location names are prohibited.

## Failure coding
Technicians select a problem, cause, and remedy code. The problem describes the observed symptom; the cause identifies why it occurred; the remedy records the corrective action. Use free text only for supporting detail. Never choose a code simply to close the work order.

## Metrics
Mean time between failures uses operating time divided by failure count. Mean time to repair uses total corrective repair time divided by corrective events. Planned-maintenance compliance compares completed scheduled work with work due in the period. Data-quality checks flag missing downtime, invalid close dates, and work orders without asset IDs.

