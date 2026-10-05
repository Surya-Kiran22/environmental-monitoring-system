import DomainView from "../components/DomainView";
import { Page } from "../components/ui";

export default function WaterQuality() {
  return (
    <Page title="Water Quality" subtitle="Water Quality Analysis Agent • pH, dissolved oxygen, turbidity, conductivity, TDS, temperature against configured ranges">
      <DomainView domain="water" />
    </Page>
  );
}
