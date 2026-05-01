import { ConfigurableForm } from "@msbc/config-ui";
import { Level3Form } from "./Level3Form.config";
import type { Level3FormSchema } from "./level3form.types";

export const Form3page = () => {

  const handleSubmit = async (data: Level3FormSchema) => {
        console.log("Typed Data:", data);
    
        try {
          alert("Submitted successfully");
        } catch (error) {
          console.error("Submission failed", error);
        }
      };
  
  return (
    <div style={{ padding: "24px" }}>
      <ConfigurableForm<Level3FormSchema>
        config={Level3Form}
        onSubmit={handleSubmit}
        defaultValues={{
          fullName: "",
          email: "",
          age: "",
          Address: "",

          gender: undefined, 
          hobbies: [],   
          country: "",
        }}
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