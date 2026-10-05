import DomainView from "../components/DomainView";
import { Page } from "../components/ui";

export default function AirQuality() {
  return (
    <Page title="Air Quality" subtitle="Air Quality Analysis Agent • PM2.5, PM10, NO₂, SO₂, CO, O₃ against configured NAAQS references">
      <DomainView domain="air" />
    </Page>
  );
}
