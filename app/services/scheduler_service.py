"""Scheduler service for background tasks like random group roasting."""

import asyncio
import logging
import random
from app.services.whatsapp import get_groups, get_group_participants, send_message, get_profile_picture_url
from app.services.image_service import analyze_group_participant_roast, download_image

logger = logging.getLogger(__name__)

async def run_random_roast_loop():
    """Background task to randomly roast a group participant every 60 minutes."""
    # We delay the first run by 60 minutes. Or maybe we can delay by 10 seconds for initial testing if needed.
    # We will stick to 3600 seconds as planned.
    while True:
        try:
            await asyncio.sleep(60)
            
            logger.info("Random Roast: Starting the 60-minute loop")
            groups = await get_groups()
            if not groups:
                logger.warning("Random Roast: No groups found")
                continue
                
            random_group = random.choice(groups)
            group_id = random_group.get("id")
            
            if not group_id:
                logger.warning("Random Roast: Selected group has no ID")
                continue
                
            participants = await get_group_participants(group_id)
            if not participants:
                logger.warning("Random Roast: No participants found in group %s", group_id)
                continue
                
            random_participant = random.choice(participants)
            
            # The participant object might have 'phoneNumber' which ends in @s.whatsapp.net
            # Or it might have 'id' which ends in @lid. We should use phoneNumber if available.
            chat_id = random_participant.get("phoneNumber")
            if not chat_id:
                # fallback if phoneNumber is not available
                chat_id = random_participant.get("id")
                
            if not chat_id:
                logger.warning("Random Roast: Selected participant has no known chat_id")
                continue
                
            # Convert @s.whatsapp.net or @lid suffix to @c.us if needed, though WAHA handles ID lookup.
            if "@s.whatsapp.net" in chat_id:
                chat_id = chat_id.replace("@s.whatsapp.net", "@c.us")
            elif "@lid" in chat_id:
                chat_id = chat_id.replace("@lid", "@c.us")
            
            logger.info("Random Roast: Selected group %s, participant %s", group_id, chat_id)
            
            pfp_url = await get_profile_picture_url(chat_id)
            pfp_bytes = await download_image(pfp_url) if pfp_url else None
            
            roast_msg = await analyze_group_participant_roast(pfp_bytes, chat_id)
            
            await send_message(group_id, roast_msg)
            logger.info("Random Roast: Successfully sent roast to group %s", group_id)
            
        except asyncio.CancelledError:
            logger.info("Random Roast Loop was cancelled. Exiting.")
            break
        except Exception as e:
            logger.exception("Random Roast Loop encountered an error: %s", str(e))
            await asyncio.sleep(60)  # Wait a bit before retrying on error
