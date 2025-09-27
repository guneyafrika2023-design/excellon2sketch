# How to run it in Fusion 360

1. Open Fusion 360 and go to the **UTILITIES** tab.  
2. Click **ADD-INS** → **Scripts and Add-Ins**.  
3. Under **Scripts**, press the **+** button to create a new **Python** script (for example, name it `ExcellonToSketch`).  
4. Open the created folder and **replace** the generated `.py` file with the provided script (same filename), or paste the code into the Fusion 360 script editor.  
5. Back in *Scripts and Add-Ins*, select your new script and click **Run**.  
6. When prompted, select your `.drl` file.  
7. After import, switch to the **Manufacture** workspace.  
8. Create a **Drill** operation and select the imported points (or circles).  
9. Post-process using the **GRBL** post-processor to generate G-code for your CNC.
