import { ConfigurableForm } from "@msbc/config-ui";
import { Level4Form } from "./Level4Form.config";
import type { Level4FormSchema } from "./level4form.types";

export const Form4page = () => {

  const handleSubmit = async (data: Level4FormSchema) => {
        console.log("Typed Data:", data);
    
        try {
          alert("Submitted successfully");
        } catch (error) {
          console.error("Submission failed", error);
        }
      };
  
  return (
    <div style={{ padding: "24px" }}>
      <ConfigurableForm<Level4FormSchema>
        config={Level4Form}
        onSubmit={handleSubmit}
        primaryButtonProps={{
          text: "Submit",
        }}
        hasSecondaryButton
        secondaryButtonProps={{
          text: "Reset",
        }}
      />
    </div>
  );
};