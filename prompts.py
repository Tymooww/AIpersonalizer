# This file contains all prompts used in the personalize_page file for easy access and maintainability
company_analysis = """You are an expert in finding the industry of email domains and company names. 
                    
                    Your task: Analyze '{company}' by searching the industry, employees and country. 

                    CRITICAL RULES:
                    1. If the item to analyze has a suffix, make sure you remove it when searching.
                    2. The industry is important so try to find it, you can use more searches if needed.
                    3. If you can't find the company size provide a -1 for company size or 'not found' for when you can't find the industry or country of the company.

                    Please provide as your answer:
                    1. Company size: this should be an estimate of the amount of employees working at the company.
                    2. Industry: the industry of the company.
                    3. Country: the country where the company is most active in.
                    4. Steps executed: provide the steps you have executed to get to your answers.

                    Information you can use:
                    Company or email domain: {company}
                    """

decide_pages_to_personalize = """Your task is to analyze and decide which pages should be personalized. 

                    Customer industry: {customer_industry}
                    Available pages: {pages}

                    For each page, decide if it could benefit from at least one of the personalizations:
                    - 'text': Personalize the text and titles
                    - 'image': Changing images to better fit the customer
                    - 'order': Reorder blocks based on customer priorities

                    Consider:
                    - Personalization is most effective on pages that have products or links to other pages listed on them.
                    - Pages without text don't need 'text' personalization
                    - Pages with less then 2 blocks don't need 'order' personalization
                    - Pages with no images don't need 'image' personalization
                    - Different industries care about different aspects
                    
                    Provide: 
                    - Personalization_list: the titles of the pages where you think personalization is valuable
                    - Explanation: the reason why you think personalization is valuable for these pages                    
                    """

decide_components_to_personalize = """Your task is to analyze which components should be personalized for the page given.

                    Customer industry: {customer_industry}
                    The page to personalize: {page_blocks}

                    For each page, decide if it needs:
                    - 'text': Personalizes the text of the page
                    - 'image': Personalizes the images of the page
                    - 'order': Personalizes the order of the page blocks based on customer priorities

                    Consider:
                    - Pages without text don't need 'text' personalization
                    - Pages with less then 2 blocks don't need 'order' personalization
                    - Pages with no images don't need 'image' personalization
                    - Different industries care about different aspects
                    - Personalization is most effective on pages that have products listed on them.
                    
                    Provide: 
                    - Personalization_list: the names of the personalization(s) you think are valuable for the customer
                    - Explanation: the reason why you think your chosen personalizations are valuable
                    """

personalize_texts = """
                    You are an expert in personalized marketing.

                    Your task: Subtly adapt "Block to personalize" to resonate with someone in the {customer_industry} sector.

                    CRITICAL RULES:
                    1. DO NOT mention the industry name, words that are very obviously related to the industry (for agriculture cultivating for example), puns or use phrases like "tailored for", "designed for", "specialized in [industry]" and don't use the same or similar wordings in every block!
                    2. DO personalize by:
                    - Emphasizing relevant challenges specific to this industry
                    - Highlighting services that solve their unique problems
                    - Using examples and scenarios they recognize
                    - Adjusting tone and focus to match their priorities
   
                    3. Example (use for reference, don't use explicitly):
                    TOO EXPLICIT: "Investment management for IT professionals in the tech sector"
                    TOO GENERIC: "Investment management for professionals"
                    JUST RIGHT: "Investment management for professionals managing equity compensation and frequent career transitions"

                    4. Stay conservative:
                    - Only adjust emphasis, examples, and specific pain points
                    - Never invent new products or services
                    - Maintain the professional tone

                    5. Content preservation:
                    - Sell the SAME products/services mentioned in the original
                    - Don't add features that weren't there
                    - Improve clarity and relevance, not scope

                    6. Output in HTML format

                    INDUSTRY CONTEXT (use implicitly, DON'T mention explicitly):
                    {customer_information}

                    ---

                    Block to personalize: {block_to_personalize}
                    Other blocks (for reference): {block_list}

                    ---

                    Provide:
                    1. Title: The personalized title (no industry name!)
                    2. Copytext: The personalized copy (HTML)
                    3. Explanation: Why these changes resonate with this audience (max 2 sentences).
            """

personalize_images = """
                You are an expert in personalized marketing.
                Your task: use "Customer information" and "Image list" to find the best fitting image(s) for the blocks in "Block list". 
                Important: 
                1. Analyze all images in "Image list" to find fitting images.
                2. You can analyze images by looking at their title, filename, description and tags.
                3. The image you choose must fit the title and/or copy of the block and should also fit with the customer's interests.
                4. Images already present in blocks can also be changed, but it is not mandatory
                5. It is mandatory to have at least TWO blocks with an image, more blocks with an image are allowed. less is not allowed, so at least TWO
                6. A block can only have one image.
                7. Every image needs to have a block to be displayed in, so there should be as many block UIDs as titles
                8. You can find the UID of a block in _metadata.
                9. Make sure that your chosen title(s) exist in "Image list", don't invent new titles but copy them over.
                10. Make sure that your chosen UID(s) exist in "Block list", don't invent new UIDs but copy them over.
                    
                Please provide as your answer:
                1. Title: this title is from the image you want to place.
                2. Block UID: this UID is from the block you want to place the image, copy it from the block list.
                3. A brief explanation of why you chose these images and why you placed them in the blocks you chose, focused on the main improvements.

                Information you can use:
                Block list: {block_list}.
                Image list: {image_list}.
                Customer information: {customer_information}.
        """

personalize_element_order = """
                You are an expert in personalized marketing.
                Your task: use "Customer information" and "Block list" to create a personalized order for the blocks of the provided page.
                Important: 
                1. Use "Customer information" to decide what blocks are the most relevant for the customer.
                2. Place the most relevant blocks first in the order. And make sure to change the place of at least one block in a different place.
                3. All blocks need to be in the list, so the amount of blocks in the Block list should be the same as the amount of UIDs given in the answer.
                4. The new order may NEVER conflict with the natural flow between the blocks, so make sure that when reading the blocks in your new order it feels like a natural flow of text.
                5. You are not allowed to change the text in the blocks.
                6. Make sure that your the UIDs of the blocks do exist in "Block list".
                7. You can find the UID of a block in _metadata.
                    
                Please provide as your answer:
                1. Block order: consisting of the UIDs of the blocks
                2. A brief explanation of why you chose this order, focused on the main improvements.

                Information you can use:
                Block list: {block_list}.
                Customer information: {customer_information}.
        """