import { ConfigurableForm } from "@msbc/config-ui";
import { Level5Form } from "./Level5Form.config";
import type { Level5FormSchema } from "./level5form.types";

export const Form5page = () => {

  const handleSubmit = async (data: Level5FormSchema) => {
        console.log("Typed Data:", data);
    
        try {
          alert("Submitted successfully");
        } catch (error) {
          console.error("Submission failed", error);
        }
      };
  
  return (
    <div style={{ padding: "24px" }}>
      <ConfigurableForm<Level5FormSchema>
        config={Level5Form}
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